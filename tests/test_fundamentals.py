"""Tests for backend/fundamentals.py.

Uses monkeypatch to inject synthetic DataFrames for backend.cache.read_ts —
no real parquet files needed. Confirms:
  - residual = con - spv - wnd holds with max|err|=0.0 MWh
  - determinism: same inputs -> same drivers
  - rejection of unknown area/focus
  - every driver carries source_curve + ts (hallucination anchor)
  - residual_check_ok=False when rdl != con - spv - wnd
  - graceful degradation when cache is empty
"""
from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def synthetic_cache(monkeypatch):
    """Inject deterministic synthetic DE data covering one demo day (96 x 15min)."""
    times = pd.date_range(
        "2026-03-06T00:00:00Z", periods=96, freq="15min", tz="UTC"
    )
    base_df = pd.DataFrame({"ts": times})

    def make(values: list[float]) -> pd.DataFrame:
        df = base_df.copy()
        df["value"] = values
        return df

    # rdl = con - spv - wnd EXACTLY (= 60000 - 20000 - 15000 = 25000).
    DATA = {
        "pri_de_spot_h": make([-16.0] * 96),
        "con_de_act": make([60000.0] * 96),
        "pro_de_spv_act": make([20000.0] * 96),
        "pro_de_wnd_act": make([15000.0] * 96),
        "rdl_de_act": make([25000.0] * 96),
        "gas_pri_nl_ttf": make([30.0] * 96),
        "co2_pri_eua": make([80.0] * 96),
    }

    def fake_read_ts(key, clock):
        df = DATA.get(key, pd.DataFrame(columns=["ts", "value"]))
        if df.empty:
            return df
        cutoff = pd.Timestamp(clock.now())
        return df[df["ts"] <= cutoff].copy()

    monkeypatch.setattr("backend.cache.read_ts", fake_read_ts)
    yield


# ---------------------------------------------------------------------------
# Happy-path: residual invariant holds, drivers are populated
# ---------------------------------------------------------------------------


def test_decompose_residual_ok_when_exact(synthetic_cache, demo_clock):
    """rdl == con - spv - wnd exactly => residual_check_ok=True, all drivers present."""
    demo_clock.tick(96)  # end of demo day
    from backend.fundamentals import decompose

    bk = decompose(
        area="DE",
        t_from="2026-03-06T00:00:00+00:00",
        t_to="2026-03-06T23:45:00+00:00",
        focus="price_crash",
        clock=demo_clock,
    )
    assert bk.residual_check_ok is True
    assert len(bk.drivers) >= 5


def test_decompose_determinism(synthetic_cache, demo_clock):
    """Same cache + same clock state => byte-identical driver values."""
    from backend.clock import VirtualNowClock
    from backend.fundamentals import decompose

    demo_clock.tick(96)
    bk1 = decompose(
        area="DE", t_from="x", t_to="y", focus="price_crash", clock=demo_clock
    )
    c2 = VirtualNowClock(demo_day=demo_clock.demo_day)
    c2.tick(96)
    bk2 = decompose(area="DE", t_from="x", t_to="y", focus="price_crash", clock=c2)
    assert [d.value for d in bk1.drivers] == [d.value for d in bk2.drivers]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_decompose_unknown_area_raises():
    from backend.clock import VirtualNowClock
    from backend.fundamentals import decompose

    with pytest.raises(ValueError):
        decompose(
            area="XX", t_from="x", t_to="y", focus="price_crash", clock=VirtualNowClock()
        )


def test_decompose_unknown_focus_raises():
    from backend.clock import VirtualNowClock
    from backend.fundamentals import decompose

    with pytest.raises(ValueError):
        decompose(
            area="DE", t_from="x", t_to="y", focus="hover", clock=VirtualNowClock()
        )


# ---------------------------------------------------------------------------
# Grounding: every driver number carries its source curve + timestamp
# ---------------------------------------------------------------------------


def test_decompose_drivers_have_sources(synthetic_cache, demo_clock):
    from backend.fundamentals import decompose

    demo_clock.tick(96)
    bk = decompose(
        area="DE", t_from="x", t_to="y", focus="price_crash", clock=demo_clock
    )
    for d in bk.drivers:
        assert d.source_curve, f"empty source_curve in {d.label}"
        assert d.ts, f"empty ts in {d.label}"


# ---------------------------------------------------------------------------
# Negative case: residual mismatch flips the flag
# ---------------------------------------------------------------------------


def test_decompose_residual_fails_on_offset(monkeypatch, demo_clock):
    """If rdl != con - spv - wnd, residual_check_ok must be False."""
    times = pd.date_range(
        "2026-03-06T00:00:00Z", periods=96, freq="15min", tz="UTC"
    )

    def fake_read_ts(key, clock):
        cutoff = pd.Timestamp(clock.now())
        VALUES = {
            "pri_de_spot_h": -16.0,
            "con_de_act": 60000.0,
            "pro_de_spv_act": 20000.0,
            "pro_de_wnd_act": 15000.0,
            "rdl_de_act": 25010.0,  # off by +10 MWh -- breaks the invariant
            "gas_pri_nl_ttf": 30.0,
            "co2_pri_eua": 80.0,
        }
        if key not in VALUES:
            return pd.DataFrame(columns=["ts", "value"])
        df = pd.DataFrame({"ts": times, "value": [VALUES[key]] * 96})
        return df[df["ts"] <= cutoff].copy()

    monkeypatch.setattr("backend.cache.read_ts", fake_read_ts)

    demo_clock.tick(96)
    from backend.fundamentals import decompose

    bk = decompose(
        area="DE", t_from="x", t_to="y", focus="price_crash", clock=demo_clock
    )
    assert bk.residual_check_ok is False


# ---------------------------------------------------------------------------
# Empty cache must not crash
# ---------------------------------------------------------------------------


def test_decompose_returns_breakdown_even_without_data(demo_clock):
    """No data in cache -> still returns a FundamentalBreakdown (no exception)."""
    from backend.fundamentals import decompose

    bk = decompose(
        area="DE", t_from="x", t_to="y", focus="price_crash", clock=demo_clock
    )
    assert bk.area == "DE"
    assert bk.focus == "price_crash"
