"""Unit tests for backend.validators — every invariant testable in isolation."""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from backend import validators
from backend.validators import (
    FORBIDDEN_COLORS,
    REQUIRED_FIXTURES,
    _check_counter_evidence_nonempty,
    _check_fixtures_present,
    _check_no_forbidden_chart_colors,
    _validate_invariants,
)


# ---------------------------------------------------------------------------
# Lenient vs strict mode (data missing)
# ---------------------------------------------------------------------------


def _point_to_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect all data paths to a tmp dir that has no curve_index / fixtures."""
    monkeypatch.setattr(validators, "CURVE_INDEX_PATH", tmp_path / "curve_index.json")
    monkeypatch.setattr(validators, "LLM_FIXTURES_DIR", tmp_path / "llm_fixtures")
    monkeypatch.setattr(
        validators, "PRECOMPUTED_BREAKDOWNS_PATH", tmp_path / "precomputed_breakdowns.json"
    )


def _stub_layouts(monkeypatch: pytest.MonkeyPatch, **attrs: object) -> None:
    """Inject a fake backend.layouts module.

    Patches BOTH sys.modules AND the parent ``backend`` package attribute so
    ``from backend import layouts`` inside the validators picks up the fake.
    """
    mod = types.ModuleType("backend.layouts")
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, "backend.layouts", mod)
    import backend  # noqa: PLC0415 — must happen after sys.modules patch is in effect

    monkeypatch.setattr(backend, "layouts", mod, raising=False)


def test_lenient_mode_no_data_returns_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_to_empty(monkeypatch, tmp_path)
    # Provide an empty-but-valid layouts module so layout-only checks return clean.
    _stub_layouts(
        monkeypatch,
        LAYOUTS={
            "de_duck_curve": {
                "windows": [
                    {"window_type": "counter", "spec": {"points": [{"claim": "x"}]}}
                ]
            },
            "de_price_crash": {
                "windows": [
                    {"window_type": "counter", "spec": {"points": [{"claim": "y"}]}}
                ]
            },
            "dk1_se4_spread": {
                "windows": [
                    {"window_type": "counter", "spec": {"points": [{"claim": "z"}]}}
                ]
            },
        },
        all_curve_keys=lambda: set(),
    )
    errors = _validate_invariants(strict=False)
    assert errors == []


def test_strict_mode_raises_when_data_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _point_to_empty(monkeypatch, tmp_path)
    _stub_layouts(
        monkeypatch,
        LAYOUTS={
            "de_duck_curve": {
                "windows": [{"window_type": "counter", "spec": {"points": [{"claim": "x"}]}}]
            },
            "de_price_crash": {
                "windows": [{"window_type": "counter", "spec": {"points": [{"claim": "y"}]}}]
            },
            "dk1_se4_spread": {
                "windows": [{"window_type": "counter", "spec": {"points": [{"claim": "z"}]}}]
            },
        },
        all_curve_keys=lambda: set(),
    )
    with pytest.raises(RuntimeError) as exc:
        _validate_invariants(strict=True)
    assert "curve_index.json missing" in str(exc.value)


# ---------------------------------------------------------------------------
# Forbidden colors
# ---------------------------------------------------------------------------


def test_check_forbidden_color_detects_logo_orange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_layouts(
        monkeypatch,
        LAYOUTS={
            "de_duck_curve": {
                "windows": [
                    {
                        "window_type": "chart",
                        "spec": {
                            "annotations": [
                                {"ts": "x", "label": "min", "color": "#ff5f00"}
                            ]
                        },
                    },
                    {"window_type": "counter", "spec": {"points": [{"claim": "c"}]}},
                ]
            },
        },
    )
    errors = _check_no_forbidden_chart_colors()
    assert any("#ff5f00" in e for e in errors)


# ---------------------------------------------------------------------------
# Counter-evidence non-empty
# ---------------------------------------------------------------------------


def test_check_counter_evidence_nonempty_detects_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_layouts(
        monkeypatch,
        LAYOUTS={
            "de_price_crash": {
                "windows": [
                    {
                        "window_type": "counter",
                        "spec": {"points": []},  # empty list → error
                    }
                ]
            },
            "de_duck_curve": {
                "windows": [
                    # No counter window at all → error
                    {"window_type": "chart"},
                ]
            },
        },
    )
    errors = _check_counter_evidence_nonempty()
    assert any("de_price_crash" in e and "no claims" in e for e in errors)
    assert any("de_duck_curve" in e and "no counter" in e for e in errors)


# ---------------------------------------------------------------------------
# Fixtures present
# ---------------------------------------------------------------------------


def test_check_fixtures_present_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Empty fixtures dir → every required fixture is reported missing.
    empty_dir = tmp_path / "llm_fixtures"
    empty_dir.mkdir()
    monkeypatch.setattr(validators, "LLM_FIXTURES_DIR", empty_dir)
    errors = _check_fixtures_present()
    assert len(errors) == len(REQUIRED_FIXTURES)
    for key in REQUIRED_FIXTURES:
        assert any(key in e for e in errors)

    # Dir totally absent → single combined error.
    monkeypatch.setattr(
        validators, "LLM_FIXTURES_DIR", tmp_path / "does_not_exist"
    )
    errors2 = _check_fixtures_present()
    assert len(errors2) == 1
    assert "llm_fixtures dir missing" in errors2[0]

    # Now place all 4 — no errors.
    monkeypatch.setattr(validators, "LLM_FIXTURES_DIR", empty_dir)
    for key in REQUIRED_FIXTURES:
        (empty_dir / f"{key}.json").write_text("{}")
    assert _check_fixtures_present() == []


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_required_fixtures_constant() -> None:
    assert len(REQUIRED_FIXTURES) == 6
    assert "haiku__apply_layout__de_duck_curve__v1" in REQUIRED_FIXTURES
    assert "haiku__apply_layout__de_price_crash__v1" in REQUIRED_FIXTURES
    assert "haiku__apply_layout__dk1_se4_spread__v1" in REQUIRED_FIXTURES
    assert "sonnet__narration__de_duck_curve_breakdown__v1" in REQUIRED_FIXTURES
    assert "sonnet__narration__de_price_crash_breakdown__v1" in REQUIRED_FIXTURES
    assert "sonnet__narration__dk1_se4_spread_breakdown__v1" in REQUIRED_FIXTURES
    # The forbidden color frozenset covers all 4 case variants of the logo orange.
    assert "#ff5f00" in FORBIDDEN_COLORS
    assert "#FF5F00" in FORBIDDEN_COLORS
    assert len(FORBIDDEN_COLORS) == 4


# ---------------------------------------------------------------------------
# Precomputed breakdowns residual check
# ---------------------------------------------------------------------------


def test_precomputed_breakdowns_strict_fails_on_false_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "precomputed_breakdowns.json"
    path.write_text(
        json.dumps(
            {
                "de_duck_curve": {"residual_check_ok": True},
                "de_price_crash": {"residual_check_ok": False},  # offending
                "dk1_se4_spread": {"residual_check_ok": True},
            }
        )
    )
    monkeypatch.setattr(validators, "PRECOMPUTED_BREAKDOWNS_PATH", path)
    errors = validators._check_precomputed_breakdowns_residual_ok(lenient=False)
    assert any("de_price_crash" in e for e in errors)
