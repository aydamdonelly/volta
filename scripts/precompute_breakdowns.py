"""Precompute FundamentalBreakdowns for the 3 thesis_keys used in the demo.

Outputs: data/precomputed_breakdowns.json
Hard-fails (exit 1) if a DE breakdown carries the full driver set (>=5 drivers)
but residual_check_ok=False — the 0-MWh invariant is non-negotiable for DE.

Usage:
  .venv/bin/python scripts/precompute_breakdowns.py [--all]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.cache import load_index
from backend.clock import VirtualNowClock
from backend.fundamentals import decompose

DEMO_DAY = date(2026, 3, 6)
OUTPUT_PATH = ROOT / "data" / "precomputed_breakdowns.json"

THESIS_CONFIG = {
    "de_duck_curve": {"area": "DE", "focus": "duck_curve"},
    "de_price_crash": {"area": "DE", "focus": "price_crash"},
    "dk1_se4_spread": {"area": "DK1", "focus": "spread"},
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--all",
        action="store_true",
        help="Compute all thesis_keys (default; reserved for future filtering).",
    )
    parser.parse_args()

    load_index()
    clock = VirtualNowClock(demo_day=DEMO_DAY)
    # Advance past the demo day so the full 24h window is visible to read_ts.
    clock.tick(steps=96)  # +24h -> 2026-04-06T00:00:00Z

    t_from = f"{DEMO_DAY.isoformat()}T00:00:00+00:00"
    t_to = f"{DEMO_DAY.isoformat()}T23:45:00+00:00"

    breakdowns: dict[str, dict] = {}
    for thesis_key, cfg in THESIS_CONFIG.items():
        print(f"Computing {thesis_key} ({cfg['area']} {cfg['focus']})...")
        bk = decompose(
            area=cfg["area"],
            t_from=t_from,
            t_to=t_to,
            focus=cfg["focus"],
            clock=clock,
        )
        breakdowns[thesis_key] = asdict(bk)
        print(
            f"  drivers={len(bk.drivers)} residual_check_ok={bk.residual_check_ok}"
        )
        if cfg["area"] == "DE" and not bk.residual_check_ok and len(bk.drivers) >= 5:
            print(
                f"  HARD-FAIL: {thesis_key} residual_check_ok=False",
                file=sys.stderr,
            )
            return 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "demo_day": DEMO_DAY.isoformat(),
        "thesis_keys": breakdowns,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    print(f"OK: wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
