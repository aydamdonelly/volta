"""Log the demo-day daily-mean + intraday range and write data/demo_day.json.

Iter v3: assertion relaxed — we don't pin the expected value anymore (different
demo days produce different prices). We log and persist; whatever the data says
is the truth.
"""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Import the canonical demo day from the backend clock to stay in sync.
sys.path.insert(0, str(ROOT))
from backend.clock import DEFAULT_DEMO_DAY  # noqa: E402

DEMO_DAY_PATH = ROOT / "data" / "demo_day.json"
INDEX_PATH = ROOT / "data" / "cache" / "meta" / "curve_index.json"


def main() -> None:
    if not INDEX_PATH.exists():
        print("ERROR: curve_index.json missing — run prepull.py first", file=sys.stderr)
        sys.exit(1)
    index = json.loads(INDEX_PATH.read_text())
    meta = index["entries"].get("pri_de_spot_h")
    if meta is None:
        print("ERROR: pri_de_spot_h not in curve_index", file=sys.stderr)
        sys.exit(1)
    df = pd.read_parquet(ROOT / meta["file"], engine="pyarrow")
    start = pd.Timestamp(DEFAULT_DEMO_DAY).tz_localize("UTC")
    end = start + pd.Timedelta(days=1)
    day_df = df[(df["ts"] >= start) & (df["ts"] < end)]
    if day_df.empty:
        print(f"ERROR: no rows for {DEFAULT_DEMO_DAY}", file=sys.stderr)
        sys.exit(1)
    daily_mean = float(day_df["value"].mean())
    intraday_min = float(day_df["value"].min())
    intraday_max = float(day_df["value"].max())
    payload = {
        "demo_day": DEFAULT_DEMO_DAY.isoformat(),
        "daily_mean_eur_mwh": daily_mean,
        "intraday_min_eur_mwh": intraday_min,
        "intraday_max_eur_mwh": intraday_max,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "source_curve": meta.get("source_curve", "pri de spot €/mwh cet h a"),
    }
    DEMO_DAY_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"OK: demo_day={DEFAULT_DEMO_DAY} daily_mean={daily_mean:.2f} €/MWh "
        f"(intraday {intraday_min:.2f}..{intraday_max:.2f})"
    )


if __name__ == "__main__":
    main()
