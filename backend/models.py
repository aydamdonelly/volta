"""Volta backend dataclasses + serialization helpers.

Plain Python 3.12 dataclasses (NOT Pydantic, per r2-backend §10). All
WS-protocol payloads (Stream #05 §3.3) and grounding types are defined here.
Module-level ``to_dict()`` / ``from_dict()`` give round-trippable JSON via
``dataclasses.asdict`` + ``dataclasses.fields`` — no third-party machinery.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Grounding primitives (ARCHITECTURE §4, Stream #05 §3.3)
# ---------------------------------------------------------------------------


@dataclass
class SourcedValue:
    """Every chart annotation / driver number must carry source_curve + ts."""

    label: str
    value: float
    unit: str
    source_curve: str
    ts: str  # ISO-8601 UTC


@dataclass
class Annotation:
    ts: str
    label: str
    color: str | None = None


@dataclass
class Claim:
    """One bullet in a counter-evidence window."""

    claim: str
    value: float
    unit: str
    source_curve: str
    ts: str


# ---------------------------------------------------------------------------
# Window-Specs (discriminated by window_type)
# ---------------------------------------------------------------------------


@dataclass
class ChartSpec:
    chart_type: Literal["line", "bar", "area"]
    x_key: str
    y_key: str
    y_unit: str
    t_from: str
    t_to: str
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class TextSpec:
    body: str
    badge: str | None
    dismissable: bool
    sources: list[SourcedValue] = field(default_factory=list)


@dataclass
class NewsSpec:
    """News-derived explanation card. ``badge`` MUST be ``context_not_proof``."""

    headline: str
    body: str
    badge: str  # convention: "context_not_proof"
    news_id: str
    severity: str  # "low" | "med" | "high"


@dataclass
class CounterSpec:
    """Counter-evidence companion (PFLICHT per ARCHITECTURE §4).

    ``badge`` MUST be ``counter_evidence``.
    """

    body: str
    badge: str  # convention: "counter_evidence"
    dismissable: bool
    points: list[Claim] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Window + Canvas
# ---------------------------------------------------------------------------


@dataclass
class Window:
    window_id: str
    theme_id: str
    window_type: str  # "chart" | "text" | "news" | "counter"
    title: str
    summary_line: str
    state: str = "small"
    curve_keys: list[str] = field(default_factory=list)
    spec: dict[str, Any] = field(default_factory=dict)
    grounding: SourcedValue | None = None
    raw_toggle: bool = True


@dataclass
class FundamentalBreakdown:
    """Deterministic residual-load decomposition (FundamentalEngine output)."""

    area: str
    focus: str  # "price_crash" | "duck_curve" | "spread"
    headline: str
    drivers: list[SourcedValue]
    method_note: str
    residual_check_ok: bool
    t_from: str
    t_to: str


@dataclass
class DerivedNewsEvent:
    news_id: str
    area: str
    severity: str  # "low" | "med" | "high"
    headline: str
    delta_value: float
    unit: str
    source_curve: str
    ts: str
    hedged: bool
    hedged_text: str


@dataclass
class WsFrame:
    """Envelope for every Server→Client WebSocket frame."""

    op: str
    seq: int
    ts: str
    payload: dict[str, Any]


@dataclass
class CanvasState:
    """Live canvas state: list of theme dicts (each holds windows)."""

    themes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CanvasSnapshot:
    """Atomic template snapshot persisted to ``data/templates/*.json``."""

    windows: list[dict[str, Any]] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    virtual_now: str = ""


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def to_dict(obj: Any) -> Any:
    """Recursively convert a dataclass (or nested structure) to plain JSON.

    Pass-through for dicts/lists/scalars so this works on already-serialized
    payloads too — that matters for the WS path where ``payload`` is a dict.
    """
    if obj is None:
        return None
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_dict(x) for x in obj]
    if isinstance(obj, tuple):
        return [to_dict(x) for x in obj]
    return obj


def from_dict(cls: type, data: dict[str, Any]) -> Any:
    """Construct a dataclass from a dict, recursing into nested dataclass fields.

    Handles the nested cases used by Volta: ``list[Annotation]``,
    ``list[SourcedValue]``, ``list[Claim]``, ``SourcedValue | None``,
    and ``FundamentalBreakdown.drivers``.
    """
    if not is_dataclass(cls):
        raise TypeError(f"from_dict expects a dataclass type, got {cls!r}")
    if data is None:
        return None
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        raw = data[f.name]
        kwargs[f.name] = _coerce(f.type, raw)
    return cls(**kwargs)


def _coerce(type_hint: Any, value: Any) -> Any:
    """Best-effort coercion of a single field value based on its annotation."""
    if value is None:
        return None
    # Annotations may arrive as strings under ``from __future__ import annotations``.
    hint = type_hint
    if isinstance(hint, str):
        # Resolve the few nested-dataclass cases we actually use.
        if "SourcedValue" in hint and isinstance(value, dict):
            return from_dict(SourcedValue, value)
        if "list[Annotation]" in hint and isinstance(value, list):
            return [from_dict(Annotation, v) if isinstance(v, dict) else v for v in value]
        if "list[SourcedValue]" in hint and isinstance(value, list):
            return [from_dict(SourcedValue, v) if isinstance(v, dict) else v for v in value]
        if "list[Claim]" in hint and isinstance(value, list):
            return [from_dict(Claim, v) if isinstance(v, dict) else v for v in value]
        return value
    # Concrete dataclass type hint.
    if is_dataclass(hint) and isinstance(value, dict):
        return from_dict(hint, value)
    return value
