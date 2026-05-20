"""Optimeering live API wrapper — replaces parquet reads for `optimeering_*` keys.

Mirrors the contract of `cache.read_optimeering(series_id, clock)` so news rule C
and the composer can route transparently.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

log = logging.getLogger("volta.optimeering_live")

# Mirror of scripts/prepull.py OPTI_FILTERS plus the curve_index.json series_ids
OPTI_KEYS: dict[str, dict] = {
    "optimeering_no1_imbalance_point":    {"area": "NO1", "product": "Imbalance", "statistic": "Point"},
    "optimeering_dk1_imbalance_point":    {"area": "DK1", "product": "Imbalance", "statistic": "Point"},
    "optimeering_se4_imbalance_point":    {"area": "SE4", "product": "Imbalance", "statistic": "Point"},
    "optimeering_no1_imbalance_quantile": {"area": "NO1", "product": "Imbalance", "statistic": "Quantile"},
    "optimeering_dk1_imbalance_quantile": {"area": "DK1", "product": "Imbalance", "statistic": "Quantile"},
    "optimeering_se4_imbalance_quantile": {"area": "SE4", "product": "Imbalance", "statistic": "Quantile"},
}

_META_BY_KEY: dict[str, dict] = {
    k: {"type": "optimeering", **v} for k, v in OPTI_KEYS.items()
}

_client_lock = threading.Lock()
_client = None
_series_id_cache: dict[str, list[int]] = {}

_TTL_OPTI_SECONDS = int(os.environ.get("OPTIMEERING_LIVE_TTL", "60"))
_TTL_SERIES_SECONDS = int(os.environ.get("OPTIMEERING_LIVE_SERIES_TTL", "600"))
_cache_data: dict[tuple, tuple[float, pd.DataFrame]] = {}
_series_cache_stamp: dict[str, float] = {}


def get_client():
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        from optimeering_beta import Configuration, OptimeeringClient
        _client = OptimeeringClient(Configuration(
            host=os.environ.get("OPTIMEERING_HOST"),
            api_key=os.environ["OPTIMEERING_API_KEY"],
        ))
        log.info("optimeering_live: client initialized")
        return _client


def list_curves() -> dict[str, Any]:
    return {k: dict(v) for k, v in _META_BY_KEY.items()}


def get_meta(series_key: str) -> dict:
    if series_key not in _META_BY_KEY:
        raise KeyError(f"unknown optimeering series_key: {series_key!r}")
    return dict(_META_BY_KEY[series_key])


def _resolve_series_ids(series_key: str) -> list[int]:
    stamp = _series_cache_stamp.get(series_key)
    if stamp is not None and time.monotonic() - stamp < _TTL_SERIES_SECONDS:
        if series_key in _series_id_cache:
            return _series_id_cache[series_key]
    meta = _META_BY_KEY[series_key]
    client = get_client()
    ser = client.predictions_api.list_series(
        area=[meta["area"]],
        product=[meta["product"]],
        statistic=[meta["statistic"]],
    )
    sids = [int(it.id) for it in (ser.items or [])]
    _series_id_cache[series_key] = sids
    _series_cache_stamp[series_key] = time.monotonic()
    return sids


def _cache_get(key: tuple):
    hit = _cache_data.get(key)
    if hit is None:
        return None
    stamp, df = hit
    if time.monotonic() - stamp > _TTL_OPTI_SECONDS:
        _cache_data.pop(key, None)
        return None
    return df


def _cache_put(key: tuple, df: pd.DataFrame) -> None:
    _cache_data[key] = (time.monotonic(), df)


def clear_caches() -> None:
    _cache_data.clear()
    _series_id_cache.clear()
    _series_cache_stamp.clear()


def fetch_predictions(
    series_key: str,
    end_ts: datetime,
    lookback: timedelta = timedelta(days=3),
) -> pd.DataFrame:
    """Fetch predictions where event_time <= end_ts. Returns wide DataFrame."""
    if series_key not in _META_BY_KEY:
        raise KeyError(f"unknown optimeering series_key: {series_key!r}")

    bucket = end_ts.replace(second=0, microsecond=0)
    cache_key = (series_key, bucket.isoformat(), int(lookback.total_seconds()))
    hit = _cache_get(cache_key)
    if hit is not None:
        return hit.copy()

    sids = _resolve_series_ids(series_key)
    if not sids:
        df = pd.DataFrame()
        _cache_put(cache_key, df)
        return df.copy()

    start_ts = end_ts - lookback
    client = get_client()
    try:
        data = client.predictions_api.retrieve(
            series_id=sids,
            start=start_ts.isoformat(),
            end=end_ts.isoformat(),
        )
        df = data.to_pandas(unpack_value_method="new_columns")
    except Exception as exc:
        log.warning("optimeering_live.fetch_predictions(%s) failed: %s", series_key, exc)
        df = pd.DataFrame()
        _cache_put(cache_key, df)
        return df.copy()

    # Normalize timezone columns
    if "event_time" in df.columns:
        if df["event_time"].dt.tz is None:
            df["event_time"] = pd.to_datetime(df["event_time"], utc=True)
        else:
            df["event_time"] = df["event_time"].dt.tz_convert("UTC")
    if "prediction_for" in df.columns:
        if df["prediction_for"].dt.tz is None:
            df["prediction_for"] = pd.to_datetime(df["prediction_for"], utc=True)
        else:
            df["prediction_for"] = df["prediction_for"].dt.tz_convert("UTC")

    # Mask: event_time <= end_ts (cache contract)
    if "event_time" in df.columns and not df.empty:
        df = df[df["event_time"] <= pd.Timestamp(end_ts)].copy()

    _cache_put(cache_key, df)
    return df.copy()
