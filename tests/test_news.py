"""Tests for backend/news.py — DerivedNewsEngine fires hedged events per rule.

Hard invariants (KB §7, phase1/10-derived-news.md):
- Every emitted event MUST have ``hedged=True`` and ``hedged_text`` containing
  "context" or "could".
- Cooldown is 30 min per ``news_id``.
- Empty cache → no events, no crash.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def utc_t() -> datetime:
    return datetime(2026, 4, 5, 14, 0, tzinfo=timezone.utc)


def _make_forecast_full(value_latest: float) -> pd.DataFrame:
    """Two issue_dates of 96 × 15-min rows — latest issue at fixed delta vs prev."""
    times = pd.date_range("2026-04-05T00:00:00Z", periods=96, freq="15min", tz="UTC")
    iss_prev = pd.Timestamp("2026-04-04T00:00:00+00:00")
    iss_latest = pd.Timestamp("2026-04-05T00:00:00+00:00")
    df_prev = pd.DataFrame({
        "ts": times,
        "value": [10000.0] * 96,
        "issue_date": iss_prev,
        "curve_key": "pro_de_spv_ec00_f",
    })
    df_latest = pd.DataFrame({
        "ts": times,
        "value": [value_latest] * 96,
        "issue_date": iss_latest,
        "curve_key": "pro_de_spv_ec00_f",
    })
    return df_prev, df_latest, pd.concat([df_prev, df_latest], ignore_index=True)


def _install_forecast_cache(monkeypatch, full_df, latest_df) -> None:
    """Patch backend.cache so rule_a (spv) sees a real diff > threshold."""
    def fake_get_meta(key: str):
        if key == "pro_de_spv_ec00_f":
            return {"file": "/tmp/fake-spv.parquet"}
        raise KeyError(key)

    def fake_read_latest(key: str, clock):
        if key == "pro_de_spv_ec00_f":
            return latest_df.copy()
        return latest_df.iloc[0:0].copy()

    monkeypatch.setattr("backend.cache.get_meta", fake_get_meta)
    monkeypatch.setattr("backend.cache._load_parquet", lambda f: full_df)
    monkeypatch.setattr("backend.cache.read_latest_instance", fake_read_latest)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_events_empty_when_no_cache(demo_clock, utc_t, monkeypatch):
    """With cache absent (or all reads raising), engine returns [] gracefully."""
    from backend.news import DerivedNewsEngine

    # Force every cache read to raise → engine must swallow and return []
    def _raise(*a, **kw):
        raise KeyError("cache not populated in this test")

    monkeypatch.setattr("backend.cache.get_meta", _raise)
    monkeypatch.setattr("backend.cache.read_ts", _raise)
    monkeypatch.setattr("backend.cache.read_latest_instance", _raise)
    monkeypatch.setattr("backend.cache.read_optimeering", _raise)

    engine = DerivedNewsEngine(clock=demo_clock)
    assert engine.events_at(utc_t) == []


def test_naive_datetime_raises(demo_clock):
    from backend.news import DerivedNewsEngine

    engine = DerivedNewsEngine(clock=demo_clock)
    with pytest.raises(ValueError):
        engine.events_at(datetime.now())


def test_rule_a_triggers_on_large_delta(demo_clock, utc_t, monkeypatch):
    """+1500 MWh latest-vs-prev delta exceeds 800 MWh spv threshold."""
    df_prev, df_latest, full = _make_forecast_full(value_latest=11500.0)
    _install_forecast_cache(monkeypatch, full, df_latest)

    from backend.news import DerivedNewsEngine

    engine = DerivedNewsEngine(clock=demo_clock)
    events = engine.events_at(utc_t)
    assert len(events) >= 1
    ev = events[0]
    assert ev.hedged is True
    assert "context" in ev.hedged_text.lower() or "could" in ev.hedged_text.lower()
    assert ev.delta_value >= 800
    assert ev.area == "DE"
    assert ev.severity in {"low", "med", "high"}


def test_rule_a_no_trigger_when_below_threshold(demo_clock, utc_t, monkeypatch):
    """+200 MWh delta is below 800 MWh threshold → no event."""
    df_prev, df_latest, full = _make_forecast_full(value_latest=10200.0)
    _install_forecast_cache(monkeypatch, full, df_latest)

    from backend.news import DerivedNewsEngine

    engine = DerivedNewsEngine(clock=demo_clock)
    assert engine.events_at(utc_t) == []


def test_rule_b_triggers_on_price_spike(demo_clock, utc_t, monkeypatch):
    """Δ of 50 €/MWh in last sample exceeds 30 EUR/MWh threshold."""
    times = pd.date_range("2026-04-05T00:00:00Z", periods=4, freq="15min", tz="UTC")
    ts_df = pd.DataFrame({
        "ts": times,
        "value": [40.0, 42.0, 41.0, 95.0],  # last delta = 54
        "curve_key": "pri_de_spot_min15",
    })

    def fake_get_meta(key: str):
        if key == "pri_de_spot_min15":
            return {"file": "/tmp/fake-spot.parquet"}
        raise KeyError(key)

    monkeypatch.setattr("backend.cache.get_meta", fake_get_meta)
    monkeypatch.setattr("backend.cache.read_ts", lambda k, c: ts_df.copy())

    from backend.news import DerivedNewsEngine

    engine = DerivedNewsEngine(clock=demo_clock)
    events = engine.events_at(utc_t)
    assert len(events) >= 1
    ev = events[0]
    assert ev.hedged is True
    assert "context" in ev.hedged_text.lower() or "could" in ev.hedged_text.lower()
    assert ev.unit == "EUR/MWh"


def test_rule_b_triggers_on_negative_price(demo_clock, utc_t, monkeypatch):
    """Negative last price fires regardless of delta magnitude."""
    times = pd.date_range("2026-04-05T00:00:00Z", periods=4, freq="15min", tz="UTC")
    ts_df = pd.DataFrame({
        "ts": times,
        "value": [10.0, 8.0, 5.0, -2.5],
        "curve_key": "pri_de_spot_min15",
    })

    def fake_get_meta(key: str):
        if key == "pri_de_spot_min15":
            return {"file": "/tmp/fake-spot.parquet"}
        raise KeyError(key)

    monkeypatch.setattr("backend.cache.get_meta", fake_get_meta)
    monkeypatch.setattr("backend.cache.read_ts", lambda k, c: ts_df.copy())

    from backend.news import DerivedNewsEngine

    engine = DerivedNewsEngine(clock=demo_clock)
    events = engine.events_at(utc_t)
    assert len(events) >= 1
    assert events[0].severity == "high"
    assert events[0].hedged is True


def test_cooldown_suppresses_second(demo_clock, utc_t, monkeypatch):
    """Within the 30-min cooldown window the same news_id is suppressed.

    Past the cooldown, Rule A only refires when a *new* issue_date crosses
    virtual_now (edge-trigger). Same fixture → no refire is the expected
    contract; a new issue_date appended later → refire.
    """
    df_prev, df_latest, full = _make_forecast_full(value_latest=11500.0)
    _install_forecast_cache(monkeypatch, full, df_latest)

    from backend.news import DerivedNewsEngine

    engine = DerivedNewsEngine(clock=demo_clock)
    e1 = engine.events_at(utc_t)
    e2 = engine.events_at(utc_t + timedelta(minutes=15))  # inside cooldown
    e3 = engine.events_at(utc_t + timedelta(minutes=31))  # past cooldown, same data
    assert len(e1) >= 1
    assert len(e2) == 0
    # Edge-trigger: same issue_date → no refire even past cooldown.
    assert len(e3) == 0

    # A genuinely new issue_date crossing the cursor → fire again.
    iss_newer = pd.Timestamp("2026-04-05T12:00:00+00:00")
    times = df_latest["ts"]
    df_newest = pd.DataFrame({
        "ts": times,
        "value": [13000.0] * len(times),
        "issue_date": iss_newer,
        "curve_key": "pro_de_spv_ec00_f",
    })
    full_with_new = pd.concat([full, df_newest], ignore_index=True)
    monkeypatch.setattr("backend.cache._load_parquet", lambda f: full_with_new)
    monkeypatch.setattr(
        "backend.cache.read_latest_instance",
        lambda k, c: df_newest.copy() if k == "pro_de_spv_ec00_f" else df_newest.iloc[0:0].copy(),
    )
    e4 = engine.events_at(utc_t + timedelta(minutes=62))
    assert len(e4) >= 1
    assert e4[0].news_id == e1[0].news_id


def test_reset_cooldowns(demo_clock, utc_t, monkeypatch):
    df_prev, df_latest, full = _make_forecast_full(value_latest=11500.0)
    _install_forecast_cache(monkeypatch, full, df_latest)

    from backend.news import DerivedNewsEngine

    engine = DerivedNewsEngine(clock=demo_clock)
    e1 = engine.events_at(utc_t)
    e2 = engine.events_at(utc_t + timedelta(minutes=5))
    engine.reset_cooldowns()
    e3 = engine.events_at(utc_t + timedelta(minutes=5))
    assert len(e1) >= 1
    assert len(e2) == 0
    assert len(e3) >= 1


def test_severity_thresholds():
    from backend.news import DerivedNewsEngine
    from backend.clock import VirtualNowClock

    engine = DerivedNewsEngine(clock=VirtualNowClock())
    assert engine._severity_for(800, 800) == "low"
    assert engine._severity_for(1200, 800) == "med"
    assert engine._severity_for(1600, 800) == "high"


def test_every_event_has_hedged_text(demo_clock, utc_t, monkeypatch):
    """Hard invariant: hedged=True and hedged_text contains 'context' or 'could'."""
    df_prev, df_latest, full = _make_forecast_full(value_latest=11500.0)
    _install_forecast_cache(monkeypatch, full, df_latest)

    from backend.news import DerivedNewsEngine

    engine = DerivedNewsEngine(clock=demo_clock)
    for ev in engine.events_at(utc_t):
        assert ev.hedged is True
        assert ev.hedged_text
        text = ev.hedged_text.lower()
        assert "context" in text or "could" in text


def test_custom_thresholds_override(demo_clock, utc_t, monkeypatch):
    """An engine started with a tiny threshold fires on small deltas."""
    df_prev, df_latest, full = _make_forecast_full(value_latest=10100.0)  # +100 MWh delta
    _install_forecast_cache(monkeypatch, full, df_latest)

    from backend.news import DerivedNewsEngine

    # 100-MWh threshold → tiny delta fires.
    engine = DerivedNewsEngine(
        clock=demo_clock,
        thresholds={"spv_forecast_delta_mwh": 50.0},
    )
    events = engine.events_at(utc_t)
    assert len(events) >= 1
    assert events[0].delta_value >= 50
