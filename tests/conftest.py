"""Volta backend test conftest. Sets sys.path + loads .env.local + provides shared fixtures."""
from __future__ import annotations
import os, sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env.local")

# Tests use the offline parquet cache + LLM fixtures by default. The real demo
# runtime overrides these to LIVE_VOLUE=1, LLM_REPLAY=0.
os.environ.setdefault("LIVE_VOLUE", "0")
os.environ.setdefault("LLM_REPLAY", "1")


@pytest.fixture
def demo_day() -> date:
    from backend.clock import DEFAULT_DEMO_DAY
    return DEFAULT_DEMO_DAY


@pytest.fixture
def demo_clock(demo_day: date):
    from backend.clock import VirtualNowClock
    return VirtualNowClock(demo_day=demo_day)


@pytest.fixture
def utc_now() -> datetime:
    from backend.clock import DEFAULT_DEMO_DAY
    return datetime(DEFAULT_DEMO_DAY.year, DEFAULT_DEMO_DAY.month, DEFAULT_DEMO_DAY.day, 14, 0, tzinfo=timezone.utc)
