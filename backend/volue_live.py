"""Volue Insight live API wrapper — replaces the parquet cache reads.

Singleton session, TTL-caching, search-first curve resolver. All returned
DataFrames use UTC tz-aware timestamps to match the existing cache contract
(so `news.py` and `cache.py` can route through here transparently).

Toggle: `LIVE_VOLUE=1` (default in production). `LIVE_VOLUE=0` falls back to
the original parquet reader in `cache.py` so the 189 existing tests still pass.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

log = logging.getLogger("volta.volue_live")

# ---------------------------------------------------------------------------
# Curve catalog (mirrors scripts/prepull.py). These are the keys callers know.
# ---------------------------------------------------------------------------

VOLUE_TS: list[tuple[str, str, str, str, str]] = [
    ("pri_de_spot_h",    "pri de spot €/mwh cet h a",                       "DE",  "EUR/MWh", "h"),
    ("pri_nl_spot_h",    "pri nl spot €/mwh cet h a",                       "NL",  "EUR/MWh", "h"),
    ("pri_be_spot_h",    "pri be spot €/mwh cet h a",                       "BE",  "EUR/MWh", "h"),
    ("pri_dk1_spot_h",   "pri dk1 spot €/mwh cet h a",                      "DK1", "EUR/MWh", "h"),
    ("pri_se4_spot_h",   "pri se4 spot €/mwh cet h a",                      "SE4", "EUR/MWh", "h"),
    ("pro_de_spv_act",   "pro de spv mwh/h cet min15 a",                    "DE",  "MWh/h",   "min15"),
    ("pro_de_wnd_act",   "pro de wnd mwh/h cet min15 a",                    "DE",  "MWh/h",   "min15"),
    ("con_de_act",       "con de mwh/h cet min15 a",                        "DE",  "MWh/h",   "min15"),
    ("rdl_de_act",       "rdl de mwh/h cet min15 sa",                       "DE",  "MWh/h",   "min15"),
    ("gas_pri_nl_ttf",   "gas pri nl ttf fut front-month clo spectron €/mwh cet d a", "NL", "EUR/MWh", "d"),
]
VOLUE_INSTANCES: list[tuple[str, str, str, str, str]] = [
    ("pro_de_spv_ec00_f", "pro de spv ec00 mwh/h cet min15 f", "DE", "MWh/h", "min15"),
    ("pro_de_wnd_ec00_f", "pro de wnd ec00 mwh/h cet min15 f", "DE", "MWh/h", "min15"),
    ("con_de_ec00_f",     "con de ec00 mwh/h cet min15 f",     "DE", "MWh/h", "min15"),
    ("rdl_de_ec00_f",     "rdl de ec00 mwh/h cet min15 f",     "DE", "MWh/h", "min15"),
]
VOLUE_TAGGED: list[tuple[str, str, str, str, str]] = [
    ("co2_pri_eua", "co2 pri ets eua €/eua cet m f", "EU", "EUR/EUA", "m"),
]

_META_BY_KEY: dict[str, dict] = {}
for k, name, area, unit, freq in VOLUE_TS:
    _META_BY_KEY[k] = {"type": "ts", "source_curve": name, "area": area, "unit": unit, "frequency": freq}
for k, name, area, unit, freq in VOLUE_INSTANCES:
    _META_BY_KEY[k] = {"type": "instance", "source_curve": name, "area": area, "unit": unit, "frequency": freq}
for k, name, area, unit, freq in VOLUE_TAGGED:
    _META_BY_KEY[k] = {"type": "ts", "source_curve": name, "area": area, "unit": unit, "frequency": freq}


# ---------------------------------------------------------------------------
# Session singleton
# ---------------------------------------------------------------------------

_session_lock = threading.Lock()
_session = None  # vit.Session
_curve_resolver_cache: dict[str, Any] = {}


def get_session():
    global _session
    if _session is not None:
        return _session
    with _session_lock:
        if _session is not None:
            return _session
        import volue_insight_timeseries as vit
        _session = vit.Session(
            urlbase=os.environ.get("VOLUE_INSIGHT_API_URL"),
            auth_urlbase=os.environ.get("VOLUE_INSIGHT_AUTH_URL"),
            client_id=os.environ["VOLUE_INSIGHT_CLIENT_ID"],
            client_secret=os.environ["VOLUE_INSIGHT_CLIENT_SECRET"],
            timeout=300,
        )
        log.info("volue_live: session initialized")
        return _session


def _resolve_curve(name: str):
    """Search-first resolver from probe_volue_deep.py. Cached per process."""
    if name in _curve_resolver_cache:
        return _curve_resolver_cache[name]
    s = get_session()
    cands = [name]
    stripped = re.sub(r"\s(ec|gfs|icon)\d+\w*", "", name)
    if stripped != name:
        cands.append(stripped)
    for cand in cands:
        hits = s.search(name=cand) or []
        if not hits:
            continue
        curve = next((h for h in hits if getattr(h, "name", None) in (name, cand)), hits[0])
        _curve_resolver_cache[name] = curve
        return curve
    # Last resort
    c = s.get_curve(name=name)
    _curve_resolver_cache[name] = c
    return c


# ---------------------------------------------------------------------------
# TTL caches
# ---------------------------------------------------------------------------

_TTL_TS_SECONDS = int(os.environ.get("VOLUE_LIVE_TS_TTL", "60"))
_TTL_INSTANCES_SECONDS = int(os.environ.get("VOLUE_LIVE_INSTANCES_TTL", "120"))
_TTL_INDEX_SECONDS = int(os.environ.get("VOLUE_LIVE_INDEX_TTL", "300"))

_cache_ts: dict[tuple, tuple[float, pd.DataFrame]] = {}
_cache_instances: dict[tuple, tuple[float, pd.DataFrame]] = {}
_cache_latest_instance: dict[tuple, tuple[float, pd.DataFrame]] = {}


def _cache_get(store: dict, key: tuple, ttl_seconds: int):
    hit = store.get(key)
    if hit is None:
        return None
    stamp, value = hit
    if time.monotonic() - stamp > ttl_seconds:
        store.pop(key, None)
        return None
    return value


def _cache_put(store: dict, key: tuple, value: pd.DataFrame) -> None:
    store[key] = (time.monotonic(), value)


def clear_caches() -> None:
    _cache_ts.clear()
    _cache_instances.clear()
    _cache_latest_instance.clear()


# ---------------------------------------------------------------------------
# Public API: matches the shape of backend/cache.py
# ---------------------------------------------------------------------------

DEFAULT_LOOKBACK = timedelta(days=30)


def list_curves() -> dict[str, Any]:
    """Returns the catalog in the same shape as cache.load_index()['entries']."""
    return {
        "version": 1,
        "entries": {k: dict(v) for k, v in _META_BY_KEY.items()},
        "demo_day": None,
        "window": None,
        "live": True,
    }


def get_meta(curve_key: str) -> dict:
    if curve_key not in _META_BY_KEY:
        raise KeyError(f"unknown curve_key: {curve_key!r}")
    return dict(_META_BY_KEY[curve_key])


def fetch_ts(curve_key: str, end_ts: datetime, lookback: timedelta = DEFAULT_LOOKBACK) -> pd.DataFrame:
    """Fetch TS rows with `ts` <= end_ts. Returns DataFrame[ts:UTC, value:float]."""
    if curve_key not in _META_BY_KEY:
        raise KeyError(f"unknown curve_key: {curve_key!r}")
    meta = _META_BY_KEY[curve_key]
    if meta["type"] != "ts":
        raise ValueError(f"{curve_key!r} is type={meta['type']!r}, not 'ts' — use fetch_instance/fetch_latest_instance")

    # Bucket end_ts to the minute so equal-minute lookups hit the same cache entry
    bucket = end_ts.replace(second=0, microsecond=0)
    cache_key = (curve_key, bucket.isoformat(), int(lookback.total_seconds()))
    hit = _cache_get(_cache_ts, cache_key, _TTL_TS_SECONDS)
    if hit is not None:
        return hit.copy()

    start_ts = end_ts - lookback
    name = meta["source_curve"]
    c = _resolve_curve(name)
    s = c.get_data(data_from=start_ts.isoformat(), data_to=end_ts.isoformat())
    if s is None:
        df = pd.DataFrame(columns=["ts", "value", "curve_key"])
    else:
        s_pd = s.to_pandas()
        if not isinstance(s_pd.index, pd.DatetimeIndex) or len(s_pd) == 0:
            df = pd.DataFrame(columns=["ts", "value", "curve_key"])
        else:
            if s_pd.index.tz is None:
                s_pd.index = s_pd.index.tz_localize("CET")
            s_utc = s_pd.tz_convert("UTC")
            df = s_utc.rename("value").reset_index()
            df.columns = ["ts", "value"]
            df["curve_key"] = curve_key
    _cache_put(_cache_ts, cache_key, df)
    return df.copy()


def fetch_latest_instance(
    curve_key: str,
    end_ts: datetime,
    lookback: timedelta = DEFAULT_LOOKBACK,
) -> pd.DataFrame:
    """Fetch the latest issue_date <= end_ts. Returns DataFrame[ts, issue_date, value]."""
    if curve_key not in _META_BY_KEY:
        raise KeyError(f"unknown curve_key: {curve_key!r}")
    meta = _META_BY_KEY[curve_key]
    if meta["type"] != "instance":
        raise ValueError(f"{curve_key!r} is type={meta['type']!r}, not 'instance'")

    bucket = end_ts.replace(second=0, microsecond=0)
    cache_key = (curve_key, bucket.isoformat(), int(lookback.total_seconds()))
    hit = _cache_get(_cache_latest_instance, cache_key, _TTL_INSTANCES_SECONDS)
    if hit is not None:
        return hit.copy()

    name = meta["source_curve"]
    c = _resolve_curve(name)
    try:
        li = c.get_latest(data_to=end_ts.isoformat())
    except Exception as exc:
        log.warning("volue_live.fetch_latest_instance(%s) failed: %s", curve_key, exc)
        df = pd.DataFrame(columns=["ts", "issue_date", "value", "curve_key"])
        _cache_put(_cache_latest_instance, cache_key, df)
        return df.copy()
    if li is None:
        df = pd.DataFrame(columns=["ts", "issue_date", "value", "curve_key"])
    else:
        lp = li.to_pandas()
        # Defensive: empty curves come back with a RangeIndex; just return empty.
        if not isinstance(lp.index, pd.DatetimeIndex) or len(lp) == 0:
            df = pd.DataFrame(columns=["ts", "issue_date", "value", "curve_key"])
        else:
            if lp.index.tz is None:
                lp.index = lp.index.tz_localize("CET")
            lp_utc = lp.tz_convert("UTC")
            issue_attr = getattr(li, "issue_date", None)
            issue_utc = (
                pd.Timestamp(issue_attr).tz_convert("UTC")
                if issue_attr is not None
                else pd.NaT
            )
            df = lp_utc.rename("value").reset_index()
            df.columns = ["ts", "value"]
            df["issue_date"] = issue_utc
            df["curve_key"] = curve_key
    _cache_put(_cache_latest_instance, cache_key, df)
    return df.copy()


def fetch_recent_instances(
    curve_key: str,
    end_ts: datetime,
    lookback: timedelta = DEFAULT_LOOKBACK,
    take_last_n: int = 5,
) -> pd.DataFrame:
    """Pull the last N issue_dates within [end_ts-lookback, end_ts]. Used by news rule A."""
    if curve_key not in _META_BY_KEY:
        raise KeyError(f"unknown curve_key: {curve_key!r}")
    meta = _META_BY_KEY[curve_key]
    if meta["type"] != "instance":
        raise ValueError(f"{curve_key!r} is type={meta['type']!r}, not 'instance'")

    bucket = end_ts.replace(second=0, microsecond=0)
    cache_key = (curve_key, bucket.isoformat(), int(lookback.total_seconds()), take_last_n)
    hit = _cache_get(_cache_instances, cache_key, _TTL_INSTANCES_SECONDS)
    if hit is not None:
        return hit.copy()

    name = meta["source_curve"]
    c = _resolve_curve(name)
    start_ts = end_ts - lookback
    try:
        meta_list = c.search_instances(
            issue_date_from=start_ts.isoformat(),
            issue_date_to=end_ts.isoformat(),
        )
    except Exception as exc:
        log.warning("volue_live.search_instances(%s) failed: %s", curve_key, exc)
        df = pd.DataFrame(columns=["ts", "issue_date", "value", "curve_key"])
        _cache_put(_cache_instances, cache_key, df)
        return df.copy()
    issue_dates = sorted({m.issue_date for m in (meta_list or [])})
    issue_dates = [d for d in issue_dates if pd.Timestamp(d).tz_convert("UTC") <= pd.Timestamp(end_ts)]
    issue_dates = issue_dates[-take_last_n:]
    if not issue_dates:
        df = pd.DataFrame(columns=["ts", "issue_date", "value", "curve_key"])
        _cache_put(_cache_instances, cache_key, df)
        return df.copy()

    rows: list[pd.DataFrame] = []
    for iss in issue_dates:
        try:
            inst = c.get_instance(
                issue_date=iss,
                data_from=start_ts.isoformat(),
                data_to=(end_ts + timedelta(days=2)).isoformat(),
            )
            if inst is None:
                continue
            ip = inst.to_pandas()
            if ip.index.tz is None:
                ip.index = ip.index.tz_localize("CET")
            ip_utc = ip.tz_convert("UTC")
            issue_utc = pd.Timestamp(iss).tz_convert("UTC")
            sub = ip_utc.rename("value").reset_index()
            sub.columns = ["ts", "value"]
            sub["issue_date"] = issue_utc
            sub["curve_key"] = curve_key
            rows.append(sub)
        except Exception as exc:
            log.debug("get_instance(%s, %s) failed: %s", curve_key, iss, exc)

    if not rows:
        df = pd.DataFrame(columns=["ts", "issue_date", "value", "curve_key"])
    else:
        df = pd.concat(rows, ignore_index=True)
        # Mask: keep only ts <= end_ts (mirror the parquet replay-filter)
        cutoff = pd.Timestamp(end_ts)
        df = df[df["ts"] <= cutoff].copy()
    _cache_put(_cache_instances, cache_key, df)
    return df.copy()
