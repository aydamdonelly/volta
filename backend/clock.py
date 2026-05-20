"""VirtualNowClock — UTC tz-aware. Pinned to demo_day (2026-03-06).

`LIVE_VOLUE=1` means the backend queries Volue's HTTPS API live each request;
it does NOT mean wall-clock. The demo time stays March 6 so the price-crash
arc + cached news rules stay coherent.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DEMO_DAY = date(2026, 3, 6)
TICK_MINUTES = 15
DEMO_DAY_JSON_DEFAULT = Path("data/demo_day.json")


class VirtualNowClock:
    """Tz-aware UTC clock advancing in 15-minute ticks from demo_day."""

    def __init__(self, demo_day: date = DEFAULT_DEMO_DAY) -> None:
        self._demo_day = demo_day
        self._cursor = datetime(
            demo_day.year, demo_day.month, demo_day.day, 0, 0, tzinfo=timezone.utc
        )
        self._tick_count = 0

    @classmethod
    def load_from_json(cls, path: Path | str = DEMO_DAY_JSON_DEFAULT) -> "VirtualNowClock":
        p = Path(path)
        if p.exists():
            payload = json.loads(p.read_text(encoding="utf-8"))
            d = date.fromisoformat(payload.get("demo_day", DEFAULT_DEMO_DAY.isoformat()))
        else:
            d = DEFAULT_DEMO_DAY
        return cls(demo_day=d)

    @property
    def demo_day(self) -> date:
        return self._demo_day

    @property
    def tick_count(self) -> int:
        return self._tick_count

    def now(self) -> datetime:
        """Return current virtual time (UTC tz-aware). Pinned to demo_day."""
        assert self._cursor.tzinfo is timezone.utc, "Clock cursor must be UTC tz-aware"
        return self._cursor

    def tick(self, steps: int = 1) -> datetime:
        if steps < 0:
            raise ValueError(f"steps must be >= 0, got {steps}")
        self._cursor = self._cursor + timedelta(minutes=TICK_MINUTES * steps)
        self._tick_count += steps
        return self._cursor

    def reset(self, to: datetime | None = None) -> datetime:
        if to is not None:
            if to.tzinfo is None:
                raise ValueError("reset target must be tz-aware")
            self._cursor = to.astimezone(timezone.utc)
        else:
            self._cursor = datetime(
                self._demo_day.year,
                self._demo_day.month,
                self._demo_day.day,
                0, 0, tzinfo=timezone.utc,
            )
        self._tick_count = 0
        return self._cursor

    def iso(self) -> str:
        return self._cursor.isoformat()
