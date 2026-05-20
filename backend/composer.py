"""AI Layout Composer — Sonnet picks 3-6 windows from the live curve catalog.

Replaces the closed-enum Haiku+apply_layout dispatch (still used as fallback in
`LIVE_VOLUE=0` / offline test mode). When `LIVE_VOLUE=1` the orchestrator calls
`compose_layout` here; Sonnet looks at the catalog + recent news + virtual_now
and emits a tool_use that pins exactly which curves go in which window types.

Validator rejects hallucinated curves (1-shot repair), clamps to [3,6] windows,
injects a counter+text window if Sonnet skipped them. Falls back to
`LAYOUTS["ad_hoc"]` if validation still fails (graceful, never crashes).
"""
from __future__ import annotations

import json
import logging
import os
import random
import uuid
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Any

log = logging.getLogger("volta.composer")

# Window-type vocabulary (mirrors models.Window.window_type)
WINDOW_TYPES = ("chart", "text", "counter", "news", "search")

# Tool schema — handed to Sonnet via tools=[COMPOSE_TOOL]
COMPOSE_TOOL: dict = {
    "name": "compose_layout",
    "description": (
        "Compose a unique 3-4 window canvas for the trader's thesis. Every "
        "chart/counter window MUST reference curve_keys from the catalog below "
        "— no inventions. Vary chart_types; include EXACTLY one counter "
        "window and EXACTLY one text window. NEVER more than 4 windows total."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "theme_label": {"type": "string", "maxLength": 80},
            "rationale_short": {"type": "string", "maxLength": 200},
            "windows": {
                "type": "array",
                "minItems": 3,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "window_type": {
                            "type": "string",
                            "enum": list(WINDOW_TYPES),
                        },
                        "title": {"type": "string", "maxLength": 80},
                        "summary_line": {"type": "string", "maxLength": 160},
                        "curve_keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "REQUIRED for chart and counter windows. Subset "
                                "of the catalog provided in the system prompt."
                            ),
                        },
                        "chart_type": {
                            "type": "string",
                            "enum": ["line", "bar", "area"],
                        },
                        "y_unit": {"type": "string"},
                        "dual_axis": {"type": "boolean"},
                        "time_range_days": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 30,
                            "description": (
                                "How many days back from virtual_now the chart "
                                "should span. 1 = current day only (00:00..23:45). "
                                "7/14/30 = last N days ending at virtual_now. Match "
                                "the trader's phrasing ('last 14 days' → 14)."
                            ),
                        },
                        "claims": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "claim": {"type": "string"},
                                    "unit": {"type": "string"},
                                    "source_curve": {"type": "string"},
                                },
                                "required": ["claim", "source_curve"],
                            },
                            "description": "REQUIRED for counter windows; ≥1.",
                        },
                        "narration_prompt_hint": {
                            "type": "string",
                            "maxLength": 240,
                        },
                        "area": {"type": "string"},
                    },
                    "required": ["window_type", "title", "summary_line"],
                },
            },
            "intent_recommendation": {"type": "string", "maxLength": 240},
        },
        "required": [
            "theme_label",
            "rationale_short",
            "windows",
            "intent_recommendation",
        ],
    },
}

EDIT_TOOL: dict = {
    "name": "edit_layout",
    "description": (
        "Modify the existing canvas in response to a natural-language instruction. "
        "Emit a sequence of operations: remove a window by id, replace one window's "
        "content with a new spec, append a new window, or reorder windows. Reuse "
        "curve_keys only from the catalog. Prefer 'replace' for swap-style edits."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ops": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["remove", "replace", "add", "reorder"]},
                        "target_window_id": {"type": "string"},
                        "new_window": {
                            "type": "object",
                            "properties": {
                                "window_type": {"type": "string", "enum": list(WINDOW_TYPES)},
                                "title": {"type": "string", "maxLength": 80},
                                "summary_line": {"type": "string", "maxLength": 160},
                                "curve_keys": {"type": "array", "items": {"type": "string"}},
                                "chart_type": {"type": "string", "enum": ["line", "bar", "area"]},
                                "y_unit": {"type": "string"},
                                "time_range_days": {
                                    "type": "integer", "minimum": 1, "maximum": 30,
                                    "description": "Same semantics as compose_layout (1=day, 7/14/30=last N).",
                                },
                                "claims": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "claim": {"type": "string"},
                                            "unit": {"type": "string"},
                                            "source_curve": {"type": "string"},
                                        },
                                        "required": ["claim", "source_curve"],
                                    },
                                },
                                "narration_prompt_hint": {"type": "string"},
                            },
                            "required": ["window_type", "title", "summary_line"],
                        },
                        "new_order": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["action"],
                },
            },
            "rationale_short": {"type": "string", "maxLength": 200},
        },
        "required": ["ops"],
    },
}

INTENT_KIND_TOOL: dict = {
    "name": "intent_kind",
    "description": (
        "Classify the trader's input as either 'edit' (modify the existing canvas) "
        "or 'compose' (start a new investigation, replacing the canvas)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["edit", "compose"]},
        },
        "required": ["kind"],
    },
}

SYSTEM_EDITOR = (
    "You are Volta — an energy trader's canvas editor at Volue. " * 3
    + "The trader already has a canvas open and just gave you a natural-language "
    "edit instruction. Translate it into a sequence of edit_layout operations.\n\n"
    "RULES:\n"
    "- 'remove' — delete a window by target_window_id.\n"
    "- 'replace' — swap one window with a fully-specified new_window (shape-preserving "
    "  when the type matches).\n"
    "- 'add' — append a new window.\n"
    "- 'reorder' — pass new_order (full permutation of current window_ids).\n"
    "- For replace/add, the new_window's curve_keys must come from the live catalog. "
    "  Counter windows must include ≥1 claim with a valid source_curve.\n"
    "- Be conservative: emit only the ops the trader actually asked for. Don't add "
    "  extras 'while you're at it'.\n"
    "- If the trader said 'swap X for Y', emit ONE 'replace' op.\n"
    "- If unclear which window to target, pick the most plausible one and explain in "
    "  rationale_short.\n"
    "- For each NEW chart window you create, set time_range_days from the trader's "
    "  text: 'today' → 1, 'last 7 days' → 7, 'last 14 days' → 14, 'last month' → 30. "
    "  NEVER label 'Last 14 Days' with time_range_days=1."
) * 2

SYSTEM_COMPOSER = (
    "You are Volta — an energy trader's canvas composer at Volue. " * 3
    + "You design a fresh, unique 3-4 window layout for every question — like "
    "a painting that is always different.\n\n"
    "HARD RULES:\n"
    "- EXACTLY 3 or 4 windows. NEVER more.\n"
    "- Always include EXACTLY ONE text window (Volta's narration target) and "
    "  EXACTLY ONE counter window (devil's advocate).\n"
    "- Every chart/counter window MUST reference curve_keys from the catalog "
    "  only. Hallucinated curve_keys will be rejected.\n"
    "- Counter window MUST have ≥1 claim. Each claim's source_curve must be a "
    "  valid source_curve string from the catalog.\n"
    "- Be diverse: a duck-curve question should not look like a price-crash "
    "  question. Use exemplars for shape only — never copy verbatim.\n"
    "- Pick frequencies that match: 15-min for intraday/forecast, hourly for "
    "  spot, daily for fuel/CO2.\n"
    "- Theme label echoes the trader's words (≤80 chars).\n"
    "- intent_recommendation = single-sentence chip in trader's language.\n"
    "- For EACH chart window, set time_range_days based on the trader's text:\n"
    "    'today' / 'now' / 'this morning' / 'afternoon' → 1\n"
    "    'last 3 days' / 'past few days' → 3\n"
    "    'last week' / 'past 7 days' → 7\n"
    "    'last 14 days' / 'fortnight' / 'past 2 weeks' → 14\n"
    "    'last month' → 30\n"
    "  Default 1 if unspecified. NEVER label a chart 'Last 14 Days' with time_range_days=1.\n"
    "Take a breath, then compose tightly."
) * 2

# Budget guard for the composer specifically
COMPOSER_TIMEOUT_S = 35.0
COMPOSER_MAX_TOKENS = 1500


# ---------------------------------------------------------------------------
# Catalog builder (cached per call)
# ---------------------------------------------------------------------------


def build_catalog_block(max_lines: int = 30) -> str:
    """Render the live Volue+Optimeering catalog as a compact text block."""
    from backend.cache import load_index

    idx = load_index()
    entries = idx.get("entries", {}) or {}
    lines: list[str] = ["AVAILABLE CURVES (curve_key | area | unit | freq | source_curve):"]
    for k, meta in list(entries.items())[:max_lines]:
        if not isinstance(meta, dict):
            continue
        area = meta.get("area", "?")
        unit = meta.get("unit", meta.get("statistic", "?"))
        freq = meta.get("frequency", meta.get("statistic", "?"))
        src = meta.get("source_curve", k)
        if meta.get("type") == "optimeering":
            src = f"optimeering {area} {meta.get('product', '')} {meta.get('statistic', '')}".strip()
        lines.append(f"- {k} | {area} | {unit} | {freq} | {src}")
    return "\n".join(lines)


def few_shot_blocks(n: int = 3) -> str:
    """Render 3 LAYOUTS as compact JSON exemplars. Seeded per UTC date for cache hit."""
    from backend.layouts import LAYOUTS

    rnd = random.Random(date.today().isoformat())
    keys = list(LAYOUTS.keys())
    sample = rnd.sample(keys, min(n, len(keys)))
    blocks: list[str] = ["Past compositions (draw inspiration, never copy verbatim):"]
    for tk in sample:
        bundle = LAYOUTS[tk]
        wins = [
            {
                "window_type": w.window_type,
                "title": w.title,
                "summary_line": w.summary_line,
                "curve_keys": w.curve_keys,
                **({"chart_type": w.extra.get("chart_type")} if w.window_type == "chart" else {}),
                **({"y_unit": w.extra.get("y_unit")} if w.window_type == "chart" else {}),
                **({"claims": w.extra.get("claims", [])} if w.window_type == "counter" else {}),
            }
            for w in bundle.windows
        ]
        blocks.append(json.dumps({"theme_label": bundle.theme_label, "windows": wins}, ensure_ascii=False))
    return "\n".join(blocks)


def recent_news_block(clock, news_engine=None, limit: int = 5) -> str:
    """Render the last `limit` derived-news headlines for context."""
    if news_engine is None:
        return "Recent news ticker: (no news_engine bound)"
    try:
        evts = news_engine.events_at(clock.now())
        lines = [f"- [{getattr(e, 'severity', '?')}] {getattr(e, 'headline', '')}" for e in evts[:limit]]
        return "Recent derived-news events:\n" + ("\n".join(lines) if lines else "  (none firing right now)")
    except Exception as exc:  # noqa: BLE001
        log.debug("recent_news_block failed: %s", exc)
        return "Recent news ticker: (unavailable)"


def build_user_prompt(user_text: str, clock, news_engine=None) -> str:
    parts: list[str] = []
    parts.append(build_catalog_block())
    parts.append("")
    parts.append(recent_news_block(clock, news_engine=news_engine))
    parts.append("")
    parts.append(f"virtual_now: {clock.now().isoformat()}")
    parts.append("")
    parts.append(few_shot_blocks())
    parts.append("")
    parts.append(f'Trader thesis:\n"{user_text}"')
    parts.append("")
    parts.append("Now compose a unique layout. Call compose_layout with your choice.")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class ComposerValidationError(RuntimeError):
    pass


def _valid_curve_keys() -> set[str]:
    from backend.cache import load_index
    return set((load_index().get("entries", {}) or {}).keys())


def _valid_source_curves() -> set[str]:
    from backend.cache import load_index
    out: set[str] = set()
    for k, m in (load_index().get("entries", {}) or {}).items():
        if not isinstance(m, dict):
            continue
        src = m.get("source_curve")
        if src:
            out.add(src.lower())
        # Optimeering: also accept the canonical "optimeering <area> <product> <stat>" form
        if m.get("type") == "optimeering":
            out.add(
                f"optimeering {m.get('area', '')} {m.get('product', '')} {m.get('statistic', '')}".strip().lower()
            )
        # Also accept the curve_key itself as a fallback identifier
        out.add(k.lower())
    return out


def validate_and_clamp(layout: dict) -> tuple[dict, list[str]]:
    """Validate Sonnet's compose_layout output. Return (cleaned_layout, issues)."""
    issues: list[str] = []
    valid_curves = _valid_curve_keys()
    valid_sources = _valid_source_curves()

    windows = list(layout.get("windows") or [])
    cleaned: list[dict] = []

    for w in windows:
        if not isinstance(w, dict):
            continue
        wt = w.get("window_type")
        if wt not in WINDOW_TYPES:
            issues.append(f"unknown window_type {wt!r} — dropped")
            continue

        if wt in ("chart", "counter"):
            curves = [c for c in (w.get("curve_keys") or []) if c in valid_curves]
            dropped = [c for c in (w.get("curve_keys") or []) if c not in valid_curves]
            for d in dropped:
                issues.append(f"{wt} dropped unknown curve_key {d!r}")
            w["curve_keys"] = curves
            if wt == "chart" and not curves:
                issues.append("chart window dropped: no valid curve_keys")
                continue

        if wt == "counter":
            claims_raw = w.get("claims") or []
            claims_clean: list[dict] = []
            for cl in claims_raw:
                if not isinstance(cl, dict):
                    continue
                sc = (cl.get("source_curve") or "").lower()
                if sc in valid_sources:
                    claims_clean.append(cl)
                else:
                    issues.append(f"counter dropped claim — unknown source_curve {sc!r}")
            w["claims"] = claims_clean
            if not claims_clean:
                issues.append("counter window dropped: no valid claims")
                continue

        cleaned.append(w)

    # Clamp to [3, 4]
    if len(cleaned) > 4:
        cleaned = cleaned[:4]
        issues.append("truncated to 4 windows")

    has_text = any(w["window_type"] == "text" for w in cleaned)
    has_counter = any(w["window_type"] == "counter" for w in cleaned)
    if not has_text:
        cleaned.append({
            "window_type": "text",
            "title": "Volta synthesis",
            "summary_line": "Sonnet writes a tailored answer.",
        })
        issues.append("injected missing text window")
    if not has_counter:
        # Inject ad_hoc counter-template
        from backend.layouts import LAYOUTS
        cleaned.append({
            "window_type": "counter",
            "title": "Counter-Evidence",
            "summary_line": "Cross-checks for sanity (context, not proof).",
            "curve_keys": ["pri_nl_spot_h", "pri_be_spot_h", "co2_pri_eua"],
            "claims": LAYOUTS["ad_hoc"].windows[2].extra.get("claims", []),
        })
        issues.append("injected missing counter window")

    if len(cleaned) < 3:
        # Pad with a "DE Spot" chart from ad_hoc
        cleaned.insert(0, {
            "window_type": "chart",
            "title": "DE Spot — Today",
            "summary_line": "Hourly day-ahead spot price.",
            "curve_keys": ["pri_de_spot_h"],
            "chart_type": "line",
            "y_unit": "€/MWh",
        })
        issues.append("padded with default DE Spot chart")

    layout["windows"] = cleaned
    return layout, issues


# ---------------------------------------------------------------------------
# Tool-output → Window dataclasses
# ---------------------------------------------------------------------------


def to_windows(layout: dict, clock) -> tuple[str, list]:
    """Convert validated layout dict to (theme_id, list[Window])."""
    from backend.layouts import _hydrate_counter_points
    from backend.models import Window

    from datetime import timedelta

    now = clock.now()
    theme_id = f"theme_composed_{uuid.uuid4().hex[:8]}"

    out: list = []
    for i, w in enumerate(layout["windows"]):
        wt = w["window_type"]
        window_id = f"win_composed_{wt}_{i}_{uuid.uuid4().hex[:6]}"
        title = w.get("title") or f"Window {i+1}"
        summary = w.get("summary_line") or ""
        curve_keys = list(w.get("curve_keys") or [])

        if wt == "chart":
            # time_range_days: 1 = current day; N>1 = last N days ending at now
            days = max(1, min(30, int(w.get("time_range_days") or 1)))
            if days == 1:
                t_from_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
                t_to_dt = now.replace(hour=23, minute=45, second=0, microsecond=0)
            else:
                t_to_dt = now
                t_from_dt = now - timedelta(days=days)
            spec = {
                "chart_type": w.get("chart_type", "line"),
                "x_key": "ts",
                "y_key": "value",
                "y_unit": w.get("y_unit", "€/MWh"),
                "t_from": t_from_dt.isoformat(),
                "t_to": t_to_dt.isoformat(),
                "annotations": [],
            }
            if w.get("dual_axis"):
                spec["dual_axis"] = True
        elif wt == "text":
            spec = {"body": "", "badge": None, "dismissable": True, "sources": []}
        elif wt == "news":
            spec = {
                "headline": "",
                "body": "",
                "badge": "context_not_proof",
                "news_id": "",
                "severity": "low",
            }
        elif wt == "counter":
            hydrated = _hydrate_counter_points(list(w.get("claims") or []), clock)
            spec = {
                "body": "",
                "badge": "counter_evidence",
                "dismissable": True,
                "points": hydrated,
            }
        elif wt == "search":
            spec = {
                "body": "",
                "query": "",
                "badge": "web_search",
                "dismissable": True,
                "hedged": True,
                "citations": [],
                "related_curve_keys": curve_keys,
            }
        else:
            continue

        # narration_prompt_hint is stashed on the window so _narrate_async can use it
        if w.get("narration_prompt_hint"):
            spec["narration_prompt_hint"] = w["narration_prompt_hint"]

        out.append(Window(
            window_id=window_id,
            theme_id=theme_id,
            window_type=wt,
            title=title,
            summary_line=summary,
            state="small",
            curve_keys=curve_keys,
            spec=spec,
            grounding=None,
            raw_toggle=True,
        ))
    return theme_id, out


# ---------------------------------------------------------------------------
# Public entrypoint: compose
# ---------------------------------------------------------------------------


def fallback_layout(thesis_hint: str | None = None) -> dict:
    """Return a deterministic ad_hoc layout dict as last-resort fallback."""
    from backend.layouts import LAYOUTS
    bundle = LAYOUTS.get(thesis_hint or "ad_hoc") or LAYOUTS["ad_hoc"]
    return {
        "theme_label": bundle.theme_label,
        "rationale_short": "Fallback layout (composer unavailable).",
        "intent_recommendation": bundle.intent_recommendation,
        "windows": [
            {
                "window_type": w.window_type,
                "title": w.title,
                "summary_line": w.summary_line,
                "curve_keys": w.curve_keys,
                **({"chart_type": w.extra.get("chart_type", "line"), "y_unit": w.extra.get("y_unit", "€/MWh")} if w.window_type == "chart" else {}),
                **({"claims": w.extra.get("claims", [])} if w.window_type == "counter" else {}),
            }
            for w in bundle.windows
        ],
    }


async def compose(
    user_text: str,
    *,
    clock,
    news_engine=None,
    thesis_hint: str | None = None,
) -> dict:
    """Call Sonnet+compose_layout; return validated layout dict.

    Falls back to `fallback_layout(thesis_hint)` on any error (timeout, budget,
    network, validator fatal). Always returns a usable layout.
    """
    import asyncio
    from backend.llm import BudgetExceeded, chat

    user_prompt = build_user_prompt(user_text, clock, news_engine=news_engine)

    try:
        r = await asyncio.wait_for(
            chat(
                model="claude-sonnet-4-6",
                system=SYSTEM_COMPOSER,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[COMPOSE_TOOL],
                tool_choice={
                    "type": "tool",
                    "name": "compose_layout",
                    "disable_parallel_tool_use": True,
                },
                max_tokens=COMPOSER_MAX_TOKENS,
                fixture_key=None,
                force_live=True,
            ),
            timeout=COMPOSER_TIMEOUT_S,
        )
    except BudgetExceeded as exc:
        log.warning("composer budget exceeded: %s — falling back", exc)
        return fallback_layout(thesis_hint)
    except Exception as exc:  # noqa: BLE001
        log.warning("composer call failed [%s: %s] — falling back", type(exc).__name__, exc)
        log.debug("composer traceback", exc_info=True)
        return fallback_layout(thesis_hint)

    # Extract the compose_layout tool_use
    layout: dict | None = None
    for blk in r.content:
        if getattr(blk, "type", None) == "tool_use" and getattr(blk, "name", None) == "compose_layout":
            layout = blk.input
            break
    if layout is None:
        log.warning("composer returned no compose_layout tool_use — falling back")
        return fallback_layout(thesis_hint)

    layout, issues = validate_and_clamp(layout)
    if issues:
        log.info("composer validator issues: %s", "; ".join(issues))
    # Final sanity check
    if len(layout.get("windows", [])) < 3:
        log.warning("composer final layout has <3 windows after fixup — falling back")
        return fallback_layout(thesis_hint)
    return layout


# ---------------------------------------------------------------------------
# Edit path (NL → canvas-mutation ops)
# ---------------------------------------------------------------------------

_EDIT_VERBS_RE = None


def heuristic_is_edit(text: str) -> bool:
    """Cheap regex sniff so we can decide without a Haiku call."""
    import re
    global _EDIT_VERBS_RE
    if _EDIT_VERBS_RE is None:
        _EDIT_VERBS_RE = re.compile(
            r"\b("
            r"swap|replace|remove|delete|drop|change|switch|"
            r"add|append|include|show me also|also show|"
            r"tausch|ersetz|entfern|l[öo]sch|wechsel|"
            r"f[üu]g.*hinzu|f[üu]g.*ein|h[äa]nge.*an"
            r")\b",
            re.IGNORECASE,
        )
    return bool(_EDIT_VERBS_RE.search(text or ""))


async def classify_intent_kind(text: str, canvas_summary: str) -> str:
    """Haiku-driven classifier. Returns 'edit' or 'compose'. Falls back to regex."""
    import asyncio
    from backend.llm import chat

    heuristic = "edit" if heuristic_is_edit(text) else "compose"
    try:
        r = await asyncio.wait_for(
            chat(
                model="claude-haiku-4-5",
                system=(
                    "You are Volta's intent classifier. Decide whether the trader is "
                    "EDITING the current canvas (swap/remove/add a card) or COMPOSING "
                    "a new one (different investigation). Call intent_kind."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Trader said: {text!r}\n\n"
                            f"Current canvas summary:\n{canvas_summary}\n\n"
                            "Call intent_kind with 'edit' or 'compose'."
                        ),
                    }
                ],
                tools=[INTENT_KIND_TOOL],
                tool_choice={"type": "tool", "name": "intent_kind", "disable_parallel_tool_use": True},
                max_tokens=64,
                fixture_key=None,
                force_live=True,
            ),
            timeout=8.0,
        )
        for blk in r.content:
            if getattr(blk, "type", None) == "tool_use" and getattr(blk, "name", None) == "intent_kind":
                kind = blk.input.get("kind")
                if kind in ("edit", "compose"):
                    return kind
    except Exception as exc:  # noqa: BLE001
        log.info("classify_intent_kind failed [%s] — heuristic=%s", exc, heuristic)
    return heuristic


def summarize_canvas_for_prompt(canvas_state: dict, max_chars: int = 800) -> str:
    """Compact human-readable summary of the current canvas for LLM prompts."""
    themes = canvas_state.get("themes") if isinstance(canvas_state, dict) else None
    if not isinstance(themes, list) or not themes:
        return "(empty canvas)"
    lines: list[str] = []
    for t in themes:
        if not isinstance(t, dict):
            continue
        wins = t.get("windows") or []
        lines.append(f"Theme '{t.get('theme_id', '?')}':")
        for w in wins:
            if not isinstance(w, dict):
                continue
            lines.append(
                f"  - {w.get('window_id', '?')} [{w.get('window_type', '?')}]: "
                f"{w.get('title', '?')} curves={w.get('curve_keys', [])}"
            )
    out = "\n".join(lines)
    return out[:max_chars] + ("…" if len(out) > max_chars else "")


async def edit(
    user_text: str,
    canvas_state: dict,
    *,
    clock,
    news_engine=None,
) -> dict:
    """Call Sonnet+edit_layout. Returns validated ops dict or {'ops': []} on failure."""
    import asyncio
    from backend.llm import BudgetExceeded, chat

    canvas_summary = summarize_canvas_for_prompt(canvas_state)
    user_prompt = (
        f"{build_catalog_block()}\n\n"
        f"{recent_news_block(clock, news_engine=news_engine)}\n\n"
        f"virtual_now: {clock.now().isoformat()}\n\n"
        f"Current canvas:\n{canvas_summary}\n\n"
        f'Trader edit instruction: "{user_text}"\n\n'
        "Now translate to edit_layout ops."
    )

    try:
        r = await asyncio.wait_for(
            chat(
                model="claude-sonnet-4-6",
                system=SYSTEM_EDITOR,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[EDIT_TOOL],
                tool_choice={"type": "tool", "name": "edit_layout", "disable_parallel_tool_use": True},
                max_tokens=COMPOSER_MAX_TOKENS,
                fixture_key=None,
                force_live=True,
            ),
            timeout=COMPOSER_TIMEOUT_S,
        )
    except (BudgetExceeded, Exception) as exc:  # noqa: BLE001
        log.warning("editor call failed [%s: %s]", type(exc).__name__, exc)
        return {"ops": [], "rationale_short": "(editor unavailable)"}

    for blk in r.content:
        if getattr(blk, "type", None) == "tool_use" and getattr(blk, "name", None) == "edit_layout":
            return blk.input or {"ops": []}
    return {"ops": [], "rationale_short": "(no tool_use returned)"}


def materialize_edit_ops(
    edit_input: dict,
    canvas_state: dict,
    *,
    clock,
    intent_id: str,
) -> list[dict]:
    """Translate edit_layout tool output → list of WS-op dicts ready for manager.emit.

    Each op dict: {"op": <name>, "payload": {...}}.
    """
    from backend.layouts import _hydrate_counter_points

    valid_curves = _valid_curve_keys()
    valid_sources = _valid_source_curves()

    # Index of theme_id per window_id in the current canvas, for spawn ops.
    theme_by_window: dict[str, str] = {}
    theme_ids: list[str] = []
    for t in canvas_state.get("themes", []) or []:
        if not isinstance(t, dict):
            continue
        tid = t.get("theme_id")
        if not tid:
            continue
        theme_ids.append(tid)
        for w in t.get("windows", []) or []:
            wid = w.get("window_id") if isinstance(w, dict) else None
            if wid:
                theme_by_window[wid] = tid

    default_theme = theme_ids[0] if theme_ids else "theme_default"

    from datetime import timedelta

    out: list[dict] = []
    now = clock.now()

    def build_window_spec(new_win: dict, wid: str, tid: str) -> dict | None:
        wt = new_win.get("window_type")
        if wt not in WINDOW_TYPES:
            return None
        curve_keys = [c for c in (new_win.get("curve_keys") or []) if c in valid_curves]
        if wt == "chart" and not curve_keys:
            return None
        if wt == "chart":
            days = max(1, min(30, int(new_win.get("time_range_days") or 1)))
            if days == 1:
                t_from_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
                t_to_dt = now.replace(hour=23, minute=45, second=0, microsecond=0)
            else:
                t_to_dt = now
                t_from_dt = now - timedelta(days=days)
            spec = {
                "chart_type": new_win.get("chart_type", "line"),
                "x_key": "ts", "y_key": "value",
                "y_unit": new_win.get("y_unit", "€/MWh"),
                "t_from": t_from_dt.isoformat(),
                "t_to": t_to_dt.isoformat(),
                "annotations": [],
            }
        elif wt == "text":
            spec = {"body": "", "badge": None, "dismissable": True, "sources": []}
        elif wt == "news":
            spec = {"headline": "", "body": "", "badge": "context_not_proof", "news_id": "", "severity": "low"}
        elif wt == "counter":
            claims = [
                cl for cl in (new_win.get("claims") or [])
                if isinstance(cl, dict) and (cl.get("source_curve") or "").lower() in valid_sources
            ]
            spec = {
                "body": "",
                "badge": "counter_evidence",
                "dismissable": True,
                "points": _hydrate_counter_points(claims, clock),
            }
        elif wt == "search":
            spec = {
                "body": "", "query": "", "badge": "web_search",
                "dismissable": True, "hedged": True, "citations": [],
                "related_curve_keys": curve_keys,
            }
        else:
            return None
        if new_win.get("narration_prompt_hint"):
            spec["narration_prompt_hint"] = new_win["narration_prompt_hint"]
        return {
            "window_id": wid,
            "theme_id": tid,
            "window_type": wt,
            "title": new_win.get("title", "Window"),
            "summary_line": new_win.get("summary_line", ""),
            "state": "small",
            "curve_keys": curve_keys,
            "spec": spec,
            "grounding": None,
            "raw_toggle": True,
            "intent_id": intent_id,
        }

    for op in edit_input.get("ops", []) or []:
        if not isinstance(op, dict):
            continue
        action = op.get("action")
        if action == "remove":
            wid = op.get("target_window_id")
            if not wid or wid not in theme_by_window:
                continue
            out.append({"op": "remove_window", "payload": {"window_id": wid, "intent_id": intent_id, "reason": "edit"}})
        elif action == "replace":
            wid = op.get("target_window_id")
            if not wid or wid not in theme_by_window:
                continue
            tid = theme_by_window[wid]
            new_win = op.get("new_window") or {}
            new_wid = f"win_edit_{new_win.get('window_type', 'x')}_{uuid.uuid4().hex[:8]}"
            spec = build_window_spec(new_win, new_wid, tid)
            if spec is None:
                continue
            out.append({
                "op": "swap_window",
                "payload": {
                    "old_window_id": wid,
                    "new_window": spec,
                    "intent_id": intent_id,
                },
            })
        elif action == "add":
            new_win = op.get("new_window") or {}
            tid = default_theme
            new_wid = f"win_edit_{new_win.get('window_type', 'x')}_{uuid.uuid4().hex[:8]}"
            spec = build_window_spec(new_win, new_wid, tid)
            if spec is None:
                continue
            out.append({"op": "spawn_window", "payload": spec})
        elif action == "reorder":
            new_order = op.get("new_order") or []
            if not new_order:
                continue
            tid = theme_by_window.get(new_order[0], default_theme)
            out.append({
                "op": "swap_window_order",
                "payload": {"theme_id": tid, "new_order": list(new_order), "intent_id": intent_id},
            })
    return out
