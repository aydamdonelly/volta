"""Pull Volue + Optimeering data to parquet cache. Window: D-14..D+2 around 2026-04-05.

Usage: scripts/prepull.py --mode=demo
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env.local")

import pandas as pd

DEMO_DAY = date(2026, 3, 6)
WINDOW_FROM = (DEMO_DAY - timedelta(days=14)).isoformat()   # 2026-03-22
WINDOW_TO_EXCLUSIVE = (DEMO_DAY + timedelta(days=3)).isoformat()  # 2026-04-08 (Volue exclusive)
CACHE_ROOT = ROOT / "data" / "cache"
TS_DIR = CACHE_ROOT / "timeseries"
INST_DIR = CACHE_ROOT / "instances"
OPTI_DIR = CACHE_ROOT / "optimeering"
META_DIR = CACHE_ROOT / "meta"
INDEX_PATH = META_DIR / "curve_index.json"

CRITICAL_KEYS = ("pri_de_spot_h", "pro_de_spv_act", "rdl_de_act")


def R(session, name: str):
    """Search-first resolver. Pattern from API_CONTRACT §1."""
    cands = [name]
    stripped = re.sub(r"\s(ec|gfs|icon)\d+\w*", "", name)
    if stripped != name:
        cands.append(stripped)
    for c in cands:
        hits = session.search(name=c) or []
        if hits:
            return next((h for h in hits if h.name in (name, c)), hits[0])
    return session.get_curve(name=name)


def save_ts(s: pd.Series, curve_key: str, path: Path) -> None:
    """Write Volue Series (CET-tz) as UTC parquet."""
    s_utc = s.tz_convert("UTC")
    df = s_utc.rename("value").reset_index()
    df.columns = ["ts", "value"]
    df["curve_key"] = curve_key
    df.to_parquet(path, engine="pyarrow", index=False, compression="snappy")


def save_instances(curve, curve_key: str, path: Path, t_from: str, t_to: str) -> None:
    """Pull recent issue_dates within window, save concatenated parquet."""
    meta = curve.search_instances(issue_date_from=t_from, issue_date_to=t_to)
    issue_dates = sorted({m.issue_date for m in (meta or [])})
    if not issue_dates:
        return
    # Take last 5
    issue_dates = issue_dates[-5:]
    rows = []
    for iss in issue_dates:
        try:
            s = curve.get_instance(issue_date=iss, data_from=t_from, data_to=t_to)
            if s is None:
                continue
            s_pd = s.to_pandas()
            s_utc = s_pd.tz_convert("UTC")
            issue_utc = pd.Timestamp(iss).tz_convert("UTC")
            df = s_utc.rename("value").reset_index()
            df.columns = ["ts", "value"]
            df["issue_date"] = issue_utc
            df["curve_key"] = curve_key
            rows.append(df)
        except Exception as e:
            print(f"  [warn] issue_date {iss}: {e}")
    if rows:
        pd.concat(rows, ignore_index=True).to_parquet(path, engine="pyarrow", index=False, compression="snappy")


def save_optimeering(df: pd.DataFrame, series_id: str, path: Path) -> None:
    # Ensure event_time + prediction_for tz-aware UTC
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
    df.to_parquet(path, engine="pyarrow", index=False, compression="snappy")


# === Curve definitions ===
# (curve_key, volue_name, area, unit, frequency)
VOLUE_TS = [
    ("pri_de_spot_h",    "pri de spot €/mwh cet h a",                       "DE", "EUR/MWh", "h"),
    ("pri_nl_spot_h",    "pri nl spot €/mwh cet h a",                       "NL", "EUR/MWh", "h"),
    ("pri_be_spot_h",    "pri be spot €/mwh cet h a",                       "BE", "EUR/MWh", "h"),
    ("pri_dk1_spot_h",   "pri dk1 spot €/mwh cet h a",                      "DK1","EUR/MWh", "h"),
    ("pri_se4_spot_h",   "pri se4 spot €/mwh cet h a",                      "SE4","EUR/MWh", "h"),
    ("pro_de_spv_act",   "pro de spv mwh/h cet min15 a",                    "DE", "MWh/h",   "min15"),
    ("pro_de_wnd_act",   "pro de wnd mwh/h cet min15 a",                    "DE", "MWh/h",   "min15"),
    ("con_de_act",       "con de mwh/h cet min15 a",                        "DE", "MWh/h",   "min15"),
    ("rdl_de_act",       "rdl de mwh/h cet min15 sa",                       "DE", "MWh/h",   "min15"),
    ("gas_pri_nl_ttf",   "gas pri nl ttf fut front-month clo spectron €/mwh cet d a", "NL","EUR/MWh","d"),
]
VOLUE_INSTANCES = [
    ("pro_de_spv_ec00_f","pro de spv ec00 mwh/h cet min15 f",                "DE", "MWh/h",   "min15"),
    ("pro_de_wnd_ec00_f","pro de wnd ec00 mwh/h cet min15 f",                "DE", "MWh/h",   "min15"),
    ("con_de_ec00_f",    "con de ec00 mwh/h cet min15 f",                    "DE", "MWh/h",   "min15"),
    ("rdl_de_ec00_f",    "rdl de ec00 mwh/h cet min15 f",                    "DE", "MWh/h",   "min15"),
]
VOLUE_TAGGED = [
    ("co2_pri_eua",      "co2 pri ets eua €/eua cet m f",                    "EU", "EUR/EUA", "m"),
]
OPTI_FILTERS = [
    ("NO1", "Imbalance", "Point"),
    ("DK1", "Imbalance", "Point"),
    ("SE4", "Imbalance", "Point"),
    ("NO1", "Imbalance", "Quantile"),
    ("DK1", "Imbalance", "Quantile"),
    ("SE4", "Imbalance", "Quantile"),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="demo", choices=["demo", "full"])
    args = parser.parse_args()

    # Ensure dirs
    for d in (TS_DIR, INST_DIR, OPTI_DIR, META_DIR):
        d.mkdir(parents=True, exist_ok=True)

    entries: dict[str, dict] = {}

    t0 = time.perf_counter()

    # --- Volue ---
    import volue_insight_timeseries as vit
    S = vit.Session(
        urlbase=os.environ["VOLUE_INSIGHT_API_URL"],
        auth_urlbase=os.environ["VOLUE_INSIGHT_AUTH_URL"],
        client_id=os.environ["VOLUE_INSIGHT_CLIENT_ID"],
        client_secret=os.environ["VOLUE_INSIGHT_CLIENT_SECRET"],
        timeout=300,
    )

    for curve_key, name, area, unit, freq in VOLUE_TS:
        try:
            c = R(S, name)
            s = c.get_data(data_from=WINDOW_FROM, data_to=WINDOW_TO_EXCLUSIVE)
            if s is None:
                print(f"  [skip] {curve_key}: get_data returned None")
                continue
            s_pd = s.to_pandas()
            path = TS_DIR / f"{curve_key}.parquet"
            save_ts(s_pd, curve_key, path)
            entries[curve_key] = {
                "type": "ts",
                "file": f"data/cache/timeseries/{curve_key}.parquet",
                "area": area,
                "unit": unit,
                "source_curve": c.name,
                "frequency": freq,
            }
            print(f"  [ok] {curve_key}: {len(s_pd)} rows")
        except Exception as e:
            print(f"  [fail] {curve_key}: {e}")

    for curve_key, name, area, unit, freq in VOLUE_INSTANCES:
        try:
            c = R(S, name)
            path = INST_DIR / f"{curve_key}.parquet"
            save_instances(c, curve_key, path, WINDOW_FROM, WINDOW_TO_EXCLUSIVE)
            if path.exists():
                entries[curve_key] = {
                    "type": "instance",
                    "file": f"data/cache/instances/{curve_key}.parquet",
                    "area": area,
                    "unit": unit,
                    "source_curve": c.name,
                    "frequency": freq,
                }
                print(f"  [ok] {curve_key}: instances saved")
        except Exception as e:
            print(f"  [fail] {curve_key}: {e}")

    for curve_key, name, area, unit, freq in VOLUE_TAGGED:
        try:
            c = R(S, name)
            s = c.get_latest(data_to=WINDOW_TO_EXCLUSIVE)
            if s is None:
                continue
            s_pd = s.to_pandas()
            path = TS_DIR / f"{curve_key}.parquet"
            save_ts(s_pd, curve_key, path)
            entries[curve_key] = {
                "type": "ts",
                "file": f"data/cache/timeseries/{curve_key}.parquet",
                "area": area,
                "unit": unit,
                "source_curve": c.name,
                "frequency": freq,
            }
            print(f"  [ok] {curve_key}: tagged latest saved")
        except Exception as e:
            print(f"  [fail] {curve_key}: {e}")

    # --- Optimeering ---
    try:
        from optimeering_beta import Configuration, OptimeeringClient
        C = OptimeeringClient(Configuration(
            host=os.environ["OPTIMEERING_HOST"],
            api_key=os.environ["OPTIMEERING_API_KEY"],
        ))
        PA = C.predictions_api

        start_iso = "2026-03-22T00:00:00+00:00"
        end_iso = "2026-04-08T00:00:00+00:00"

        for area, product, statistic in OPTI_FILTERS:
            try:
                ser = PA.list_series(area=[area], product=[product], statistic=[statistic])
                if not ser.items:
                    print(f"  [skip] optimeering {area} {product} {statistic}: no series")
                    continue
                series_ids = [it.id for it in ser.items]
                data = PA.retrieve(series_id=series_ids, start=start_iso, end=end_iso)
                df = data.to_pandas(unpack_value_method="new_columns")
                key = f"optimeering_{area.lower()}_{product.lower()}_{statistic.lower()}"
                path = OPTI_DIR / f"{key}.parquet"
                save_optimeering(df, key, path)
                entries[key] = {
                    "type": "optimeering",
                    "file": f"data/cache/optimeering/{key}.parquet",
                    "area": area,
                    "product": product,
                    "statistic": statistic,
                    "series_ids": series_ids,
                }
                print(f"  [ok] {key}: {len(df)} rows")
            except Exception as e:
                print(f"  [fail] optimeering {area} {product} {statistic}: {e}")
    except Exception as e:
        print(f"  [fail] optimeering setup: {e}")

    # Write index
    index = {
        "version": 1,
        "demo_day": DEMO_DAY.isoformat(),
        "window": [WINDOW_FROM, WINDOW_TO_EXCLUSIVE],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }
    INDEX_PATH.write_text(json.dumps(index, indent=2, sort_keys=True, default=str), encoding="utf-8")

    elapsed = time.perf_counter() - t0
    print(f"\nDONE: {len(entries)} curves in {elapsed:.1f}s")

    # Hard-fail if critical keys missing
    missing = [k for k in CRITICAL_KEYS if k not in entries]
    if missing:
        print(f"CRITICAL keys missing: {missing}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
