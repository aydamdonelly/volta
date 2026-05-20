"""Standalone smoke check: invariants, demo-day, fixtures, fundamentals determinism.

Exit 0 if all checks pass; exit 1 otherwise.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    failures: list[str] = []

    def check(name, fn):
        try:
            fn()
            print(f"  [ok]   {name}")
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failures.append(name)

    # 1. curve_index present
    check("curve_index.json exists", lambda: (ROOT / "data/cache/meta/curve_index.json").stat())

    # 2. demo_day matches DEFAULT_DEMO_DAY and daily mean is a real non-trivial number
    def _demo():
        from backend.clock import DEFAULT_DEMO_DAY
        p = json.loads((ROOT / "data/demo_day.json").read_text())
        assert p["demo_day"] == DEFAULT_DEMO_DAY.isoformat(), f"demo_day {p['demo_day']}"
        assert abs(p["daily_mean_eur_mwh"]) > 50, f"daily mean {p['daily_mean_eur_mwh']}"
    check("demo_day matches DEFAULT_DEMO_DAY + mean meaningful", _demo)

    # 3. precomputed all ok
    def _precomp():
        p = json.loads((ROOT / "data/precomputed_breakdowns.json").read_text())
        bks = p["thesis_keys"]
        for tk in ("de_duck_curve", "de_price_crash", "dk1_se4_spread"):
            assert bks[tk]["residual_check_ok"] is True, f"{tk}"
    check("precomputed 3 thesis_keys residual_check_ok=True", _precomp)

    # 4. fixtures
    def _fix():
        d = ROOT / "data/llm_fixtures"
        for n in (
            "haiku__apply_layout__de_duck_curve__v1",
            "haiku__apply_layout__de_price_crash__v1",
            "haiku__apply_layout__dk1_se4_spread__v1",
            "sonnet__narration__de_price_crash_breakdown__v1",
        ):
            assert (d / f"{n}.json").exists(), n
    check("4 LLM fixtures present", _fix)

    # 5. boot validators
    def _val():
        from backend.validators import _validate_invariants
        errs = _validate_invariants(strict=False)
        if errs:
            raise AssertionError(f"{len(errs)} errors: {errs[:3]}")
    check("validators(strict=False) returns 0 errors", _val)

    # 6. cache load + read DE price
    def _cache():
        from backend.cache import load_index, read_ts, clear_cache
        from backend.clock import VirtualNowClock
        clear_cache(); load_index()
        c = VirtualNowClock(); c.tick(96)
        df = read_ts("pri_de_spot_h", c)
        assert len(df) > 0
    check("cache reads pri_de_spot_h", _cache)

    # 7. fundamentals determinism
    def _fund():
        from backend.clock import DEFAULT_DEMO_DAY, VirtualNowClock
        from backend.fundamentals import decompose
        day = DEFAULT_DEMO_DAY.isoformat()
        t_from = f"{day}T00:00:00+00:00"
        t_to = f"{day}T23:45:00+00:00"
        c = VirtualNowClock(); c.tick(96)
        c2 = VirtualNowClock(); c2.tick(96)
        b1 = decompose(area="DE", t_from=t_from, t_to=t_to, focus="price_crash", clock=c)
        b2 = decompose(area="DE", t_from=t_from, t_to=t_to, focus="price_crash", clock=c2)
        assert [d.value for d in b1.drivers] == [d.value for d in b2.drivers], "non-deterministic"
        assert b1.residual_check_ok is True
        price = next(d for d in b1.drivers if "price" in d.label.lower())
        assert abs(price.value) > 50, f"demo-day price not meaningful: {price.value}"
    check("fundamentals deterministic + demo-day price meaningful", _fund)

    if failures:
        print(f"\nFAILED: {len(failures)}")
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
