"""Cache facade — dispatches to live Volue/Optimeering APIs or to local parquet.

`LIVE_VOLUE` env flag:
  - `1` (default): all reads hit `volue_live` / `optimeering_live` (real Volue Insight + Optimeering APIs, TTL-cached).
  - `0`: legacy parquet reader (preserved for the 189 backend tests).

The public contract — `load_index`, `get_meta`, `read_ts`, `read_instance`,
`read_latest_instance`, `read_optimeering`, `clear_cache` — is unchanged so
`news.py`, `orchestrator.py`, `main.py` route through transparently.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger("volta.cache")

ROOT = Path(__file__).resolve().parent.parent
CACHE_ROOT = ROOT / "data" / "cache"
INDEX_PATH = CACHE_ROOT / "meta" / "curve_index.json"

_INDEX: dict[str, Any] | None = None


def _live_mode() -> bool:
    return os.environ.get("LIVE_VOLUE", "1") == "1"


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------


def _live_index() -> dict[str, Any]:
    from backend import volue_live, optimeering_live
    entries: dict[str, dict] = dict(volue_live.list_curves()["entries"])
    entries.update(optimeering_live.list_curves())
    return {
        "version": 1,
        "demo_day": None,
        "window": None,
        "entries": entries,
        "live": True,
    }


def load_index() -> dict[str, Any]:
    """Load curve catalog. Live mode → assemble from API wrappers; offline → parquet json."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    if _live_mode():
        _INDEX = _live_index()
        return _INDEX
    if not INDEX_PATH.exists():
        _INDEX = {"version": 1, "entries": {}}
        return _INDEX
    payload = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    if "entries" not in payload:
        payload["entries"] = {}
    _INDEX = payload
    return _INDEX


def get_meta(curve_key: str) -> dict:
    if _INDEX is None:
        load_index()
    entries = _INDEX["entries"]  # type: ignore[index]
    if curve_key not in entries:
        raise KeyError(f"unknown curve_key: {curve_key!r}")
    return entries[curve_key]


# ---------------------------------------------------------------------------
# Parquet helpers (offline mode only)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=64)
def _load_parquet(file: str) -> pd.DataFrame:
    df = pd.read_parquet(file, engine="pyarrow")
    ts_col = None
    if "ts" in df.columns:
        ts_col = "ts"
    elif "event_time" in df.columns:
        ts_col = "event_time"
    if ts_col is not None:
        tz = df[ts_col].dt.tz
        if tz is None or str(tz) != "UTC":
            raise RuntimeError(
                f"{file}: {ts_col} column must be UTC tz-aware, got tz={tz}"
            )
    return df


def _resolve_path(meta_file: str) -> str:
    p = Path(meta_file)
    return str(p) if p.is_absolute() else str(ROOT / p)


# ---------------------------------------------------------------------------
# Read API (live or parquet)
# ---------------------------------------------------------------------------


def read_ts(curve_key: str, clock) -> pd.DataFrame:
    """TS read masked by `df.ts <= clock.now()`."""
    if _live_mode():
        from backend import volue_live
        from datetime import timedelta
        end_ts = clock.now()
        return volue_live.fetch_ts(curve_key, end_ts, lookback=timedelta(days=30))
    meta = get_meta(curve_key)
    df = _load_parquet(_resolve_path(meta["file"]))
    cutoff = pd.Timestamp(clock.now())
    return df[df["ts"] <= cutoff].copy()


def read_instance(curve_key: str, issue_date: str, clock) -> pd.DataFrame:
    """Specific INSTANCES issue_date, masked by clock.now().

    Live mode: pulls recent instances and filters to the requested issue_date.
    """
    if _live_mode():
        from backend import volue_live
        from datetime import timedelta
        end_ts = clock.now()
        df = volue_live.fetch_recent_instances(curve_key, end_ts, lookback=timedelta(days=14), take_last_n=20)
        iss = pd.Timestamp(issue_date)
        if iss.tzinfo is None:
            iss = iss.tz_localize("UTC")
        return df[df["issue_date"] == iss].copy()
    meta = get_meta(curve_key)
    df = _load_parquet(_resolve_path(meta["file"]))
    cutoff = pd.Timestamp(clock.now())
    iss = pd.Timestamp(issue_date)
    return df[(df["issue_date"] == iss) & (df["ts"] <= cutoff)].copy()


def read_latest_instance(curve_key: str, clock) -> pd.DataFrame:
    """Latest issue_date <= clock.now(). Empty DataFrame if none yet."""
    if _live_mode():
        from backend import volue_live
        from datetime import timedelta
        end_ts = clock.now()
        return volue_live.fetch_latest_instance(curve_key, end_ts, lookback=timedelta(days=14))
    meta = get_meta(curve_key)
    df = _load_parquet(_resolve_path(meta["file"]))
    cutoff = pd.Timestamp(clock.now())
    valid = df[df["issue_date"] <= cutoff]
    if valid.empty:
        return df.iloc[0:0].copy()
    latest_iss = valid["issue_date"].max()
    return df[(df["issue_date"] == latest_iss) & (df["ts"] <= cutoff)].copy()


def get_instance_history(curve_key: str, clock) -> pd.DataFrame:
    """All [ts, value, issue_date, curve_key] rows from the latest ~10 issue dates.

    Used by news rule A (forecast revision). The caller (news.py) applies its
    own `issue_date <= t` mask, so this returns unfiltered history.
    """
    if _live_mode():
        from backend import volue_live
        from datetime import timedelta
        end_ts = clock.now()
        return volue_live.fetch_recent_instances(
            curve_key, end_ts, lookback=timedelta(days=14), take_last_n=10
        )
    meta = get_meta(curve_key)
    return _load_parquet(_resolve_path(meta["file"])).copy()


def read_optimeering(series_id: str, clock) -> pd.DataFrame:
    if _live_mode():
        from backend import optimeering_live
        from datetime import timedelta
        end_ts = clock.now()
        return optimeering_live.fetch_predictions(series_id, end_ts, lookback=timedelta(days=3))
    meta = get_meta(series_id)
    df = _load_parquet(_resolve_path(meta["file"]))
    cutoff = pd.Timestamp(clock.now())
    return df[df["event_time"] <= cutoff].copy()


def clear_cache() -> None:
    """Test utility: reset module state (index + parquet LRU + live caches)."""
    global _INDEX
    _INDEX = None
    _load_parquet.cache_clear()
    if _live_mode():
        try:
            from backend import volue_live, optimeering_live
            volue_live.clear_caches()
            optimeering_live.clear_caches()
        except Exception:
            pass
