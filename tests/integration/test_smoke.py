"""Integration smoke + determinism + demo-day invariants. Requires populated data/."""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"


def test_curve_index_has_all_expected_keys():
    idx = json.loads((DATA / "cache" / "meta" / "curve_index.json").read_text())
    entries = idx["entries"]
    expected = ["pri_de_spot_h", "pro_de_spv_act", "pro_de_wnd_act", "con_de_act", "rdl_de_act",
                "pro_de_spv_ec00_f", "pro_de_wnd_ec00_f", "con_de_ec00_f", "rdl_de_ec00_f",
                "pri_dk1_spot_h", "pri_se4_spot_h", "gas_pri_nl_ttf", "co2_pri_eua"]
    for key in expected:
        assert key in entries, f"missing {key}"
    # Optimeering: at least 3 series for NO1/DK1/SE4
    opti = [k for k in entries if k.startswith("optimeering_")]
    assert len(opti) >= 3, f"only {len(opti)} optimeering entries"


def test_demo_day_mean_within_tolerance():
    from backend.clock import DEFAULT_DEMO_DAY
    payload = json.loads((DATA / "demo_day.json").read_text())
    assert payload["demo_day"] == DEFAULT_DEMO_DAY.isoformat()
    # March 6 is a winter spot day — daily mean should be a real, non-trivial number.
    assert abs(payload["daily_mean_eur_mwh"]) > 50


def test_precomputed_breakdowns_all_residual_ok():
    payload = json.loads((DATA / "precomputed_breakdowns.json").read_text())
    bks = payload["thesis_keys"]
    for tk in ("de_duck_curve", "de_price_crash", "dk1_se4_spread"):
        assert tk in bks, f"missing {tk}"
        assert bks[tk]["residual_check_ok"] is True, f"{tk} residual_check_ok=False"


def test_all_4_fixtures_present():
    fix_dir = DATA / "llm_fixtures"
    for name in (
        "haiku__apply_layout__de_duck_curve__v1",
        "haiku__apply_layout__de_price_crash__v1",
        "haiku__apply_layout__dk1_se4_spread__v1",
        "sonnet__narration__de_price_crash_breakdown__v1",
    ):
        p = fix_dir / f"{name}.json"
        assert p.exists(), f"missing fixture {name}"
        d = json.loads(p.read_text())
        assert "response" in d
        assert d["response"].get("stop_reason") in ("tool_use", "end_turn", "stop_sequence")


def test_parquet_files_all_utc():
    import pyarrow.parquet as pq
    idx = json.loads((DATA / "cache" / "meta" / "curve_index.json").read_text())
    for key, meta in idx["entries"].items():
        p = ROOT / meta["file"]
        schema = pq.read_schema(str(p))
        for col in ("ts", "event_time"):
            if col in schema.names:
                tz = getattr(schema.field(col).type, "tz", None)
                assert tz is not None and str(tz).upper() == "UTC", f"{key} {col} tz={tz}"


def test_cache_lazy_load_replay_mask():
    from backend.cache import load_index, read_ts, clear_cache
    from backend.clock import VirtualNowClock
    clear_cache()
    load_index()
    clock = VirtualNowClock()  # demo-day 00:00 UTC
    df = read_ts("pri_de_spot_h", clock)
    assert not df.empty
    # At 00:00 UTC of demo day, all data through midnight should be present (but cap = 00:00 inclusive -> 1 row at most for that ts)
    cutoff = clock.now()
    assert df["ts"].max() <= pd.Timestamp(cutoff)


def test_fundamentals_decompose_determinism():
    from backend.clock import DEFAULT_DEMO_DAY, VirtualNowClock
    from backend.fundamentals import decompose
    day = DEFAULT_DEMO_DAY.isoformat()
    t_from = f"{day}T00:00:00+00:00"
    t_to = f"{day}T23:45:00+00:00"
    c1 = VirtualNowClock()
    c1.tick(96)  # end of demo day
    c2 = VirtualNowClock()
    c2.tick(96)
    bk1 = decompose(area="DE", t_from=t_from, t_to=t_to, focus="price_crash", clock=c1)
    bk2 = decompose(area="DE", t_from=t_from, t_to=t_to, focus="price_crash", clock=c2)
    assert [d.value for d in bk1.drivers] == [d.value for d in bk2.drivers]
    assert bk1.residual_check_ok is True


def test_fundamentals_de_price_driver_is_real_number():
    """Demo-day daily-mean DE Spot must be a plausible real number (not zero, not NaN)."""
    from backend.clock import DEFAULT_DEMO_DAY, VirtualNowClock
    from backend.fundamentals import decompose
    day = DEFAULT_DEMO_DAY.isoformat()
    c = VirtualNowClock()
    c.tick(96)
    bk = decompose(area="DE", t_from=f"{day}T00:00:00+00:00", t_to=f"{day}T23:45:00+00:00", focus="price_crash", clock=c)
    price = next((d for d in bk.drivers if "price" in d.label.lower()), None)
    assert price is not None, f"no price driver in {bk.drivers}"
    assert abs(price.value) > 50, f"demo-day price not meaningful: {price.value}"


def test_news_engine_events_demo_day_have_hedge():
    from backend.clock import VirtualNowClock
    from backend.news import DerivedNewsEngine
    c = VirtualNowClock()
    c.tick(56)  # 14:00 UTC on demo day
    engine = DerivedNewsEngine(clock=c)
    events = engine.events_at(c.now())
    for ev in events:
        assert ev.hedged is True
        assert any(p in ev.hedged_text.lower() for p in ("context", "could"))


def test_clock_tick_15_min_increments():
    from backend.clock import VirtualNowClock
    c = VirtualNowClock()
    base = c.now()
    c.tick(1)
    assert (c.now() - base).total_seconds() == 900  # 15 min
    c.tick(95)
    assert (c.now() - base).total_seconds() == 96 * 900  # 24h


def test_clock_dst_transparent():
    """UTC is DST-blind; cache reads at 01:30 and 02:30 UTC on 2026-03-29 work identically."""
    from datetime import datetime, timezone
    from backend.clock import VirtualNowClock
    from backend.cache import read_ts, clear_cache, load_index
    clear_cache()
    load_index()
    c = VirtualNowClock()
    c.reset(datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc))
    df1 = read_ts("pri_de_spot_h", c)
    c.reset(datetime(2026, 3, 29, 2, 30, tzinfo=timezone.utc))
    df2 = read_ts("pri_de_spot_h", c)
    assert len(df2) >= len(df1), "tick across DST should not lose rows"
