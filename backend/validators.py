"""Startup invariants for the Volta backend.

`_validate_invariants(strict=True)` is meant to run inside the FastAPI
lifespan handler. In strict mode any failure raises a single ``RuntimeError``
listing every violation, so a misconfigured cache is fail-loud.

Lenient mode (``strict=False``) is for build-time and tests: when
``data/cache/meta/curve_index.json`` doesn't exist yet we skip data-dependent
checks gracefully so other modules can still import without a populated cache.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_FIXTURES: tuple[str, ...] = (
    "haiku__apply_layout__de_duck_curve__v1",
    "haiku__apply_layout__de_price_crash__v1",
    "haiku__apply_layout__dk1_se4_spread__v1",
    "sonnet__narration__de_duck_curve_breakdown__v1",
    "sonnet__narration__de_price_crash_breakdown__v1",
    "sonnet__narration__dk1_se4_spread_breakdown__v1",
)

# Volue-Logo-Orange — banned from charts/themes per Wave styling lock.
FORBIDDEN_COLORS: frozenset[str] = frozenset(
    {"#ff5f00", "#FF5F00", "#Ff5f00", "#fF5F00"}
)

# Defaults — module-level so tests can monkeypatch them.
ROOT = Path(__file__).resolve().parent.parent
CURVE_INDEX_PATH = ROOT / "data" / "cache" / "meta" / "curve_index.json"
LLM_FIXTURES_DIR = ROOT / "data" / "llm_fixtures"
PRECOMPUTED_BREAKDOWNS_PATH = ROOT / "data" / "precomputed_breakdowns.json"

THESIS_KEYS = ("de_duck_curve", "de_price_crash", "dk1_se4_spread")


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def _validate_invariants(strict: bool = True) -> list[str]:
    """Run all data + layout invariants. Return list of error strings.

    In strict mode, raise ``RuntimeError`` if any error is found.
    In lenient mode (build-time), skip data-dependent checks if the cache
    index file is absent and return only structural errors.
    """
    errors: list[str] = []

    cache_exists = CURVE_INDEX_PATH.exists()

    if not cache_exists and not strict:
        # Build-time / pre-prepull: data layer not populated yet. We still run
        # layout/code-only checks that don't depend on parquet files.
        errors.extend(_check_no_forbidden_chart_colors())
        errors.extend(_check_counter_evidence_nonempty())
        return errors

    # From here on, either strict OR cache exists.
    if cache_exists:
        errors.extend(_check_curve_index_exists())
        errors.extend(_check_parquet_files_utc())
        errors.extend(_check_layouts_curve_keys_valid())
    else:
        # strict + no cache → that's the first error
        errors.append(f"curve_index.json missing at {CURVE_INDEX_PATH}")

    errors.extend(_check_no_forbidden_chart_colors())
    errors.extend(_check_counter_evidence_nonempty())
    errors.extend(_check_fixtures_present())
    errors.extend(_check_precomputed_breakdowns_residual_ok(lenient=not strict))

    if strict and errors:
        raise RuntimeError(
            "INVARIANT VIOLATIONS (" + str(len(errors)) + "):\n  - " + "\n  - ".join(errors)
        )
    return errors


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_curve_index_exists() -> list[str]:
    """The cache must be populated with a curve_index containing 'entries'."""
    if not CURVE_INDEX_PATH.exists():
        return [f"curve_index.json missing at {CURVE_INDEX_PATH}"]
    try:
        with CURVE_INDEX_PATH.open() as f:
            idx = json.load(f)
    except json.JSONDecodeError as exc:
        return [f"curve_index.json is not valid JSON: {exc}"]
    if not isinstance(idx, dict) or "entries" not in idx:
        return ["curve_index.json missing required 'entries' key"]
    return []


def _check_parquet_files_utc() -> list[str]:
    """Each parquet entry exists on disk + ts/event_time column is UTC tz-aware."""
    if not CURVE_INDEX_PATH.exists():
        return []
    try:
        with CURVE_INDEX_PATH.open() as f:
            idx = json.load(f)
    except json.JSONDecodeError:
        return []
    entries = idx.get("entries") if isinstance(idx, dict) else None
    if not isinstance(entries, dict):
        return []

    errors: list[str] = []
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return ["pyarrow not installed — cannot verify parquet schemas"]

    for curve_key, meta in entries.items():
        if not isinstance(meta, dict):
            continue
        file_path = meta.get("file")
        if not file_path:
            errors.append(f"{curve_key}: missing 'file' in curve_index entry")
            continue
        p = Path(file_path)
        if not p.is_absolute():
            p = ROOT / p
        if not p.exists():
            errors.append(f"{curve_key}: parquet file missing at {p}")
            continue
        try:
            schema = pq.read_schema(str(p))
        except Exception as exc:  # noqa: BLE001 — parquet errors are heterogeneous
            errors.append(f"{curve_key}: failed to read parquet schema: {exc}")
            continue

        ts_field = None
        for candidate in ("ts", "event_time"):
            if candidate in schema.names:
                ts_field = schema.field(candidate)
                break
        if ts_field is None:
            errors.append(f"{curve_key}: parquet has no 'ts' or 'event_time' column")
            continue
        # pyarrow.timestamp(unit, tz=...) — tz attr is the string 'UTC' or None
        tz = getattr(ts_field.type, "tz", None)
        if tz is None or str(tz).upper() != "UTC":
            errors.append(
                f"{curve_key}: ts/event_time tz={tz!r}, expected 'UTC' (tz-aware)"
            )
    return errors


def _check_layouts_curve_keys_valid() -> list[str]:
    """Every curve_key referenced by a layout must exist in the index.

    Lazy-imports ``backend.layouts.all_curve_keys()`` (set[str]). If the module
    isn't importable for any reason, this check is silently a no-op so import
    cycles don't block startup.
    """
    try:
        from backend import layouts  # noqa: PLC0415 — lazy on purpose
    except Exception:  # noqa: BLE001 — layouts might not exist yet
        return []
    if not hasattr(layouts, "all_curve_keys"):
        return []

    try:
        used: set[str] = set(layouts.all_curve_keys())
    except Exception as exc:  # noqa: BLE001
        return [f"layouts.all_curve_keys() raised: {exc}"]
    if not used:
        return []

    if not CURVE_INDEX_PATH.exists():
        return []
    try:
        with CURVE_INDEX_PATH.open() as f:
            idx = json.load(f)
    except json.JSONDecodeError:
        return []
    entries = idx.get("entries") if isinstance(idx, dict) else {}
    known = set(entries.keys()) if isinstance(entries, dict) else set()

    errors: list[str] = []
    for key in used:
        # Optimeering keys look like "opti_<area>_<product>_..." — accept those
        # as long as the layouts module recognised them.
        if key in known:
            continue
        if key.startswith("opti_"):
            continue
        errors.append(f"layout references unknown curve_key {key!r}")
    return errors


def _check_no_forbidden_chart_colors() -> list[str]:
    """Recursively scan layouts.LAYOUTS for any banned-orange substring."""
    try:
        from backend import layouts  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return []
    bundles = getattr(layouts, "LAYOUTS", None)
    if bundles is None:
        return []

    hits: list[str] = []

    def _scan(obj: Any, path: str = "LAYOUTS") -> None:
        if isinstance(obj, str):
            for color in FORBIDDEN_COLORS:
                if color in obj:
                    hits.append(f"forbidden color {color!r} found at {path}")
                    break
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                _scan(v, f"{path}.{k}")
            return
        if isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                _scan(v, f"{path}[{i}]")
            return
        # Dataclass / object — walk its __dict__ if any
        d = getattr(obj, "__dict__", None)
        if isinstance(d, dict):
            for k, v in d.items():
                _scan(v, f"{path}.{k}")

    _scan(bundles)
    return hits


def _check_counter_evidence_nonempty() -> list[str]:
    """Every layout bundle must include ≥1 counter window with ≥1 claim/point."""
    try:
        from backend import layouts  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return []
    bundles = getattr(layouts, "LAYOUTS", None)
    if not isinstance(bundles, dict):
        return []

    errors: list[str] = []
    for thesis_key, bundle in bundles.items():
        counter_windows = _find_counter_windows(bundle)
        if not counter_windows:
            errors.append(f"{thesis_key}: no counter-evidence window present")
            continue
        ok = False
        for win in counter_windows:
            if _counter_points(win):
                ok = True
                break
        if not ok:
            errors.append(
                f"{thesis_key}: counter window present but has no claims/points"
            )
    return errors


def _find_counter_windows(bundle: Any) -> list[Any]:
    """Walk a layout bundle (dict|list|dataclass) and yield counter-typed windows."""
    out: list[Any] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            wt = node.get("window_type")
            if wt == "counter":
                out.append(node)
            for v in node.values():
                _walk(v)
            return
        if isinstance(node, (list, tuple)):
            for v in node:
                _walk(v)
            return
        # Dataclass-like
        wt_attr = getattr(node, "window_type", None)
        if wt_attr == "counter":
            out.append(node)
        d = getattr(node, "__dict__", None)
        if isinstance(d, dict):
            for v in d.values():
                _walk(v)

    _walk(bundle)
    return out


def _counter_points(window: Any) -> list[Any]:
    """Extract points/claims list from a counter window of any shape."""
    if isinstance(window, dict):
        spec = window.get("spec") or window.get("extra") or {}
        if isinstance(spec, dict):
            pts = spec.get("points") or spec.get("claims") or []
            if isinstance(pts, list):
                return pts
        return []
    spec = getattr(window, "spec", None) or getattr(window, "extra", None)
    if isinstance(spec, dict):
        pts = spec.get("points") or spec.get("claims") or []
        if isinstance(pts, list):
            return pts
    pts = getattr(spec, "points", None) if spec is not None else None
    if isinstance(pts, list):
        return pts
    return []


def _check_fixtures_present() -> list[str]:
    """Every required LLM-fixture file (.json) must exist on disk."""
    if not LLM_FIXTURES_DIR.exists():
        return [f"llm_fixtures dir missing at {LLM_FIXTURES_DIR}: " + ", ".join(REQUIRED_FIXTURES)]
    errors: list[str] = []
    for key in REQUIRED_FIXTURES:
        if not (LLM_FIXTURES_DIR / f"{key}.json").exists():
            errors.append(f"missing LLM fixture: {key}.json")
    return errors


def _check_precomputed_breakdowns_residual_ok(lenient: bool = False) -> list[str]:
    """All 3 thesis_keys in precomputed_breakdowns.json must have residual_check_ok=True."""
    if not PRECOMPUTED_BREAKDOWNS_PATH.exists():
        if lenient:
            return []
        return [f"precomputed_breakdowns.json missing at {PRECOMPUTED_BREAKDOWNS_PATH}"]
    try:
        with PRECOMPUTED_BREAKDOWNS_PATH.open() as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        return [f"precomputed_breakdowns.json is not valid JSON: {exc}"]

    # Support both top-level shape and the canonical {"thesis_keys": {...}} envelope
    container = data.get("thesis_keys") if isinstance(data, dict) and "thesis_keys" in data else data

    errors: list[str] = []
    for thesis in THESIS_KEYS:
        if thesis not in container:
            errors.append(f"precomputed_breakdowns: missing thesis_key {thesis!r}")
            continue
        bd = container[thesis]
        if not isinstance(bd, dict) or not bd.get("residual_check_ok", False):
            errors.append(
                f"precomputed_breakdowns[{thesis!r}].residual_check_ok != True"
            )
    return errors
