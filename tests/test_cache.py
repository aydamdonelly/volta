"""Tests for backend/cache.py — UTC tz-aware Parquet read layer with LRU cache.

All tests use `tmp_path` + monkeypatch of `backend.cache.CACHE_ROOT` and
`backend.cache.INDEX_PATH` so no real `data/cache/` is touched. Synthetic
parquet is generated in-test (UTC tz-aware on write).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from backend import cache as cache_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect CACHE_ROOT/INDEX_PATH to tmp_path; reset module state per test."""
    cache_root = tmp_path / "cache"
    meta_dir = cache_root / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    index_path = meta_dir / "curve_index.json"

    monkeypatch.setattr(cache_mod, "CACHE_ROOT", cache_root)
    monkeypatch.setattr(cache_mod, "INDEX_PATH", index_path)
    # Also redirect ROOT so meta["file"] relative paths resolve under tmp_path.
    monkeypatch.setattr(cache_mod, "ROOT", tmp_path)

    cache_mod.clear_cache()
    yield
    cache_mod.clear_cache()


class _FixedClock:
    """Minimal clock stub returning a fixed UTC tz-aware datetime."""

    def __init__(self, when: datetime) -> None:
        self._when = when

    def now(self) -> datetime:
        return self._when


# ---------------------------------------------------------------------------
# Parquet helpers
# ---------------------------------------------------------------------------


def _write_ts_parquet(
    path: Path, *, n_rows: int = 96, start: str = "2026-04-05T00:00:00Z"
) -> None:
    times = pd.date_range(start=start, periods=n_rows, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "ts": times,
            "value": [float(i) for i in range(n_rows)],
            "curve_key": "test_ts",
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, engine="pyarrow", index=False, compression="snappy")


def _write_optimeering_parquet(
    path: Path, *, n_rows: int = 96, start: str = "2026-04-05T00:00:00Z"
) -> None:
    times = pd.date_range(start=start, periods=n_rows, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "series_id": ["no1_imb"] * n_rows,
            "version": ["1.2.1"] * n_rows,
            "event_time": times,
            "prediction_for": times,
            "value_point": [float(i) for i in range(n_rows)],
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, engine="pyarrow", index=False, compression="snappy")


def _write_instances_parquet(
    path: Path,
    *,
    issue_dates: list[str],
    n_rows_per_issue: int = 8,
    start: str = "2026-04-05T00:00:00Z",
) -> None:
    rows: list[pd.DataFrame] = []
    for iss in issue_dates:
        times = pd.date_range(
            start=start, periods=n_rows_per_issue, freq="15min", tz="UTC"
        )
        issue_ts = pd.Timestamp(iss)
        if issue_ts.tzinfo is None:
            issue_ts = issue_ts.tz_localize("UTC")
        else:
            issue_ts = issue_ts.tz_convert("UTC")
        rows.append(
            pd.DataFrame(
                {
                    "ts": times,
                    "value": [float(i) for i in range(n_rows_per_issue)],
                    "issue_date": [issue_ts] * n_rows_per_issue,
                    "curve_key": "test_inst",
                }
            )
        )
    df = pd.concat(rows, ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, engine="pyarrow", index=False, compression="snappy")


def _write_index(index_path: Path, entries: dict) -> None:
    payload = {"version": 1, "entries": entries}
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_load_index_returns_empty_when_missing():
    # INDEX_PATH was created by the fixture's meta dir but the file does not exist.
    assert not cache_mod.INDEX_PATH.exists()
    idx = cache_mod.load_index()
    assert idx == {"version": 1, "entries": {}}


def test_load_index_parses_valid_json():
    entries = {
        "test_ts": {
            "file": "cache/timeseries/test_ts.parquet",
            "curve_type": "TS",
            "unit": "MWh",
            "area": "DE",
            "tz": "UTC",
        }
    }
    _write_index(cache_mod.INDEX_PATH, entries)
    idx = cache_mod.load_index()
    assert idx["entries"] == entries
    assert idx["entries"]["test_ts"]["unit"] == "MWh"


def test_get_meta_raises_for_unknown():
    cache_mod.load_index()
    with pytest.raises(KeyError):
        cache_mod.get_meta("does_not_exist")


def test_load_parquet_asserts_utc_tz_aware(tmp_path: Path):
    # Write a non-UTC tz-aware parquet (CET).
    parquet = tmp_path / "cache" / "timeseries" / "cet.parquet"
    parquet.parent.mkdir(parents=True, exist_ok=True)
    times = pd.date_range(
        start="2026-04-05T00:00:00", periods=4, freq="15min", tz="Europe/Berlin"
    )
    df = pd.DataFrame({"ts": times, "value": [1.0, 2.0, 3.0, 4.0]})
    df.to_parquet(parquet, engine="pyarrow", index=False)

    with pytest.raises(RuntimeError, match="must be UTC tz-aware"):
        cache_mod._load_parquet(str(parquet))


def test_load_parquet_lru_cache(tmp_path: Path):
    parquet = tmp_path / "cache" / "timeseries" / "ts_lru.parquet"
    _write_ts_parquet(parquet, n_rows=8)
    # Two reads of the same path: second must be a cache hit.
    cache_mod._load_parquet(str(parquet))
    cache_mod._load_parquet(str(parquet))
    info = cache_mod._load_parquet.cache_info()
    assert info.hits >= 1
    assert info.maxsize == 64


def test_read_ts_replay_mask(tmp_path: Path):
    parquet = tmp_path / "cache" / "timeseries" / "ts_replay.parquet"
    _write_ts_parquet(parquet, n_rows=96, start="2026-04-05T00:00:00Z")

    _write_index(
        cache_mod.INDEX_PATH,
        {"test_ts": {"file": "cache/timeseries/ts_replay.parquet", "curve_type": "TS"}},
    )
    cache_mod.load_index()

    clock = _FixedClock(datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc))
    df = cache_mod.read_ts("test_ts", clock)
    # 00:00, 00:15, ..., 12:00 inclusive → 49 rows.
    assert len(df) == 49
    assert df["ts"].max() == pd.Timestamp("2026-04-05T12:00:00", tz="UTC")


def test_read_optimeering_event_time_mask(tmp_path: Path):
    parquet = tmp_path / "cache" / "optimeering" / "no1_imb.parquet"
    _write_optimeering_parquet(parquet, n_rows=96, start="2026-04-05T00:00:00Z")

    _write_index(
        cache_mod.INDEX_PATH,
        {
            "optimeering_no1_imbalance_point": {
                "file": "cache/optimeering/no1_imb.parquet",
                "curve_type": "OPTIMEERING",
            }
        },
    )
    cache_mod.load_index()

    clock = _FixedClock(datetime(2026, 4, 5, 6, 0, tzinfo=timezone.utc))
    df = cache_mod.read_optimeering("optimeering_no1_imbalance_point", clock)
    # 00:00..06:00 inclusive → 25 rows.
    assert len(df) == 25
    assert df["event_time"].max() == pd.Timestamp("2026-04-05T06:00:00", tz="UTC")


def test_read_instance_filters_by_issue_date(tmp_path: Path):
    parquet = tmp_path / "cache" / "instances" / "inst.parquet"
    _write_instances_parquet(
        parquet,
        issue_dates=["2026-04-03T00:00:00Z", "2026-04-04T00:00:00Z"],
        n_rows_per_issue=4,
    )
    _write_index(
        cache_mod.INDEX_PATH,
        {
            "test_inst": {
                "file": "cache/instances/inst.parquet",
                "curve_type": "INSTANCES",
            }
        },
    )
    cache_mod.load_index()

    clock = _FixedClock(datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc))
    df = cache_mod.read_instance("test_inst", "2026-04-04T00:00:00Z", clock)
    assert len(df) == 4
    assert (df["issue_date"] == pd.Timestamp("2026-04-04T00:00:00Z")).all()


def test_read_latest_instance_picks_latest_before_cutoff(tmp_path: Path):
    parquet = tmp_path / "cache" / "instances" / "latest.parquet"
    _write_instances_parquet(
        parquet,
        issue_dates=[
            "2026-04-03T00:00:00Z",
            "2026-04-04T00:00:00Z",
            "2026-04-06T00:00:00Z",  # future relative to the clock below
        ],
        n_rows_per_issue=4,
    )
    _write_index(
        cache_mod.INDEX_PATH,
        {
            "test_latest": {
                "file": "cache/instances/latest.parquet",
                "curve_type": "INSTANCES",
            }
        },
    )
    cache_mod.load_index()

    # Cutoff at 2026-04-05T12:00Z: 04-04 issue is the latest valid issue_date;
    # all 4 of its ts rows (2026-04-05 00:00..00:45) precede the cutoff; the
    # 04-06 issue is in the future and excluded.
    clock = _FixedClock(datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc))
    df = cache_mod.read_latest_instance("test_latest", clock)
    assert (df["issue_date"] == pd.Timestamp("2026-04-04T00:00:00Z")).all()
    assert len(df) == 4


def test_read_latest_instance_empty_when_no_valid_issue(tmp_path: Path):
    parquet = tmp_path / "cache" / "instances" / "future.parquet"
    _write_instances_parquet(
        parquet,
        issue_dates=["2026-04-06T00:00:00Z"],
        n_rows_per_issue=4,
    )
    _write_index(
        cache_mod.INDEX_PATH,
        {
            "future_only": {
                "file": "cache/instances/future.parquet",
                "curve_type": "INSTANCES",
            }
        },
    )
    cache_mod.load_index()

    clock = _FixedClock(datetime(2026, 4, 5, 0, 0, tzinfo=timezone.utc))
    df = cache_mod.read_latest_instance("future_only", clock)
    assert df.empty


def test_clear_cache_resets_state(tmp_path: Path):
    parquet = tmp_path / "cache" / "timeseries" / "ts_reset.parquet"
    _write_ts_parquet(parquet, n_rows=4)
    _write_index(
        cache_mod.INDEX_PATH,
        {"test_ts": {"file": "cache/timeseries/ts_reset.parquet", "curve_type": "TS"}},
    )
    cache_mod.load_index()
    cache_mod._load_parquet(str(parquet))
    assert cache_mod._INDEX is not None
    assert cache_mod._load_parquet.cache_info().currsize >= 1

    cache_mod.clear_cache()
    assert cache_mod._INDEX is None
    assert cache_mod._load_parquet.cache_info().currsize == 0
