"""Unit tests for backend.clock.VirtualNowClock."""
from __future__ import annotations
import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.clock import (
    DEFAULT_DEMO_DAY,
    TICK_MINUTES,
    VirtualNowClock,
)


def test_default_demo_day_mar6() -> None:
    """Demo-day defaults to 2026-03-06."""
    c = VirtualNowClock()
    assert c.demo_day == date(2026, 3, 6)
    assert DEFAULT_DEMO_DAY == date(2026, 3, 6)


def test_now_is_utc_tz_aware() -> None:
    """now() always returns a tz-aware datetime anchored in timezone.utc."""
    c = VirtualNowClock()
    n = c.now()
    assert n.tzinfo is timezone.utc
    assert n.year == 2026 and n.month == 3 and n.day == 6
    assert n.hour == 0 and n.minute == 0


def test_tick_15_min() -> None:
    """A single tick advances exactly 15 minutes."""
    c = VirtualNowClock()
    before = c.now()
    after = c.tick(1)
    assert after - before == timedelta(minutes=TICK_MINUTES)
    assert after.tzinfo is timezone.utc
    assert c.tick_count == 1


def test_tick_56_is_14h() -> None:
    """56 ticks = 14 hours → 2026-03-06T14:00:00Z."""
    c = VirtualNowClock()
    c.tick(56)
    assert c.now() == datetime(2026, 3, 6, 14, 0, tzinfo=timezone.utc)
    assert c.tick_count == 56


def test_tick_96_is_24h() -> None:
    """96 ticks = 24 hours → 2026-03-07T00:00:00Z (full day rollover)."""
    c = VirtualNowClock()
    c.tick(96)
    assert c.now() == datetime(2026, 3, 7, 0, 0, tzinfo=timezone.utc)


def test_reset_default_returns_to_demo_day_zero() -> None:
    """reset() with no args returns cursor to demo_day 00:00 UTC and zeroes tick_count."""
    c = VirtualNowClock()
    c.tick(40)
    assert c.now() != datetime(2026, 3, 6, 0, 0, tzinfo=timezone.utc)
    returned = c.reset()
    assert returned == datetime(2026, 3, 6, 0, 0, tzinfo=timezone.utc)
    assert c.now() == datetime(2026, 3, 6, 0, 0, tzinfo=timezone.utc)
    assert c.tick_count == 0


def test_reset_to_specific_utc() -> None:
    """reset(target) with a tz-aware datetime moves cursor to that UTC moment."""
    c = VirtualNowClock()
    target = datetime(2026, 3, 6, 12, 30, tzinfo=timezone.utc)
    returned = c.reset(to=target)
    assert returned == target
    assert c.now() == target
    assert c.tick_count == 0


def test_reset_to_specific_non_utc_tz_converts_to_utc() -> None:
    """A tz-aware datetime in another tz is converted to UTC on reset."""
    c = VirtualNowClock()
    cet = ZoneInfo("Europe/Berlin")
    # 2026-03-06 14:00 CET = 13:00 UTC (DST not yet active in early March 2026).
    target_cet = datetime(2026, 3, 6, 14, 0, tzinfo=cet)
    c.reset(to=target_cet)
    assert c.now() == datetime(2026, 3, 6, 13, 0, tzinfo=timezone.utc)
    assert c.now().tzinfo is timezone.utc


def test_reset_naive_raises() -> None:
    """Resetting to a naive datetime raises ValueError (tz-contract guard)."""
    c = VirtualNowClock()
    with pytest.raises(ValueError):
        c.reset(to=datetime(2026, 3, 6, 12, 0))


def test_tick_negative_raises() -> None:
    """Negative tick steps raise ValueError (clock only marches forward)."""
    c = VirtualNowClock()
    with pytest.raises(ValueError):
        c.tick(-1)


def test_tick_zero_is_noop() -> None:
    """tick(0) does not advance and does not increment tick_count."""
    c = VirtualNowClock()
    before = c.now()
    after = c.tick(0)
    assert after == before
    assert c.tick_count == 0


def test_load_from_json_present(tmp_path: Path) -> None:
    """load_from_json reads demo_day from JSON when file exists."""
    p = tmp_path / "demo_day.json"
    p.write_text(json.dumps({"demo_day": "2026-03-06"}), encoding="utf-8")
    c = VirtualNowClock.load_from_json(p)
    assert c.demo_day == date(2026, 3, 6)
    assert c.now() == datetime(2026, 3, 6, 0, 0, tzinfo=timezone.utc)


def test_load_from_json_alternate_day(tmp_path: Path) -> None:
    """load_from_json honours a non-default demo_day."""
    p = tmp_path / "demo_day.json"
    p.write_text(json.dumps({"demo_day": "2026-01-01"}), encoding="utf-8")
    c = VirtualNowClock.load_from_json(p)
    assert c.demo_day == date(2026, 1, 1)


def test_load_from_json_absent(tmp_path: Path) -> None:
    """Missing JSON file falls back to DEFAULT_DEMO_DAY."""
    p = tmp_path / "does_not_exist.json"
    c = VirtualNowClock.load_from_json(p)
    assert c.demo_day == DEFAULT_DEMO_DAY


def test_dst_transition_transparent() -> None:
    """UTC is DST-blind: timestamps either side of CET spring-forward stay tz-aware UTC."""
    c = VirtualNowClock()
    pre = datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc)
    post = datetime(2026, 3, 29, 2, 30, tzinfo=timezone.utc)
    c.reset(to=pre)
    assert c.now() == pre and c.now().tzinfo is timezone.utc
    c.reset(to=post)
    assert c.now() == post and c.now().tzinfo is timezone.utc
    # Exactly one hour of separation, no anomaly in UTC.
    assert post - pre == timedelta(hours=1)


def test_iso_returns_iso_8601_with_offset() -> None:
    """iso() includes an explicit UTC offset (+00:00 from stdlib datetime.isoformat)."""
    c = VirtualNowClock()
    s = c.iso()
    assert s.startswith("2026-03-06T00:00:00")
    assert ("+00:00" in s) or s.endswith("Z")


def test_iso_updates_after_tick() -> None:
    """iso() reflects the cursor position after ticks."""
    c = VirtualNowClock()
    c.tick(4)  # +1h
    assert c.iso().startswith("2026-03-06T01:00:00")


def test_tick_count_accumulates_across_calls() -> None:
    """Multiple tick() calls accumulate steps; reset zeroes the counter."""
    c = VirtualNowClock()
    c.tick(2)
    c.tick(3)
    assert c.tick_count == 5
    c.reset()
    assert c.tick_count == 0


def test_explicit_demo_day_constructor() -> None:
    """Constructor accepts arbitrary demo_day and anchors cursor at its 00:00 UTC."""
    c = VirtualNowClock(demo_day=date(2026, 1, 1))
    assert c.demo_day == date(2026, 1, 1)
    assert c.now() == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
