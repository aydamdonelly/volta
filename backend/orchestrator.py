"""Orchestrator — AI-composed layout (live mode) OR Tier-1 Haiku apply_layout (legacy).

Live mode (`LIVE_VOLUE=1`, default): `_handle_thesis` calls
`composer.compose()` → Sonnet picks 3-6 windows from the live curve catalog.
The layout is unique per intent — "a painting that is always different."

Legacy mode (`LIVE_VOLUE=0`, used by tests): regex-fast-path / Haiku classify →
layouts.resolve → fixed bundle for one of 4 thesis_keys.

UC2 (news_id click): same shape, news-framed compose.

UC2 (news_id click): map news_id → curve_key + thesis_key, decompose the area,
emit spawn_theme + 4 spawn_window (chart + text + counter + news), fire a
live Sonnet narration that explains the event in market context, then done.

All WS ops are emitted via ConnectionManager.emit() in strict order; the manager
takes care of seq, ts envelope, ringpuffer and per-client queues.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from backend.clock import DEFAULT_DEMO_DAY, TICK_MINUTES

ROOT = Path(__file__).resolve().parent.parent
PRECOMPUTED_PATH = ROOT / "data" / "precomputed_breakdowns.json"
log = logging.getLogger("volta.orchestrator")

THESIS_KEYS = ("de_duck_curve", "de_price_crash", "dk1_se4_spread", "ad_hoc")
# Sub-set that has regex fast-path + precomputed breakdown fixtures.
BAKED_THESIS_KEYS = ("de_duck_curve", "de_price_crash", "dk1_se4_spread")

# Regex fast-path (zero-cost) when input clearly signals a known thesis.
# Ordering: price_crash beats duck_curve when both could match (April-5/negative wins).
THESIS_PATTERNS: dict[str, re.Pattern[str]] = {
    "de_price_crash": re.compile(
        r"(price.?crash|negative.*price|preis.*absturz|"
        r"march.?6|m[äa]rz.?6|2026-03-06|crash.*germany|negative.*spot|"
        r"april.?5|2026-04-05|easter|ostern)",
        re.I,
    ),
    "dk1_se4_spread": re.compile(
        r"(dk1.{0,6}se4|denmark.{0,6}sweden|spread.*nordic|"
        r"cross.?border.*nordic|imbalance.*nordic|no1|se4)",
        re.I,
    ),
    "de_duck_curve": re.compile(
        r"(duck.?curve|solar.*spread|mittag.*preis|mittagstief|"
        r"solar surplus|midday|solar.*duck|germany.*solar)",
        re.I,
    ),
}

# System prompts. Padded with repetition so static blocks meet the Haiku ≥2048
# token threshold for prompt-caching (phase1/01 §2.8, R6).
SYSTEM_HAIKU = (
    "You are Volta, an energy trader's copilot at Volue. " * 3
    + "Your job is to map a trader's verbal thesis to ONE predefined demo layout via "
    "the apply_layout tool. "
    "Allowed thesis_key values: de_duck_curve, de_price_crash, dk1_se4_spread, ad_hoc. " * 2
    + "Choose the closest semantic match. Never invent thesis_keys. "
    "If the user mentions Germany, solar, midday → de_duck_curve. "
    "If the user mentions negative prices, April 5, price crash, Easter weekend → "
    "de_price_crash. "
    "If the user mentions DK1, SE4, Nordic, spread, imbalance → dk1_se4_spread. "
    "If the trader's question doesn't fit any baked thesis (e.g. carbon, gas, "
    "France, UK, weather, capacity, regulation, an open-ended exploratory query) "
    "→ choose ad_hoc and the LLM will synthesize a layout. "
    "Always provide a 'theme' display label." * 4
)

SYSTEM_SONNET_NARRATION = (
    "You are Volta narrating a fundamental breakdown to an energy trader. "
    "Be concise (2-3 sentences). ALWAYS cite the source_curve and ts inline in "
    "parentheses. NEVER invent numbers — only reuse values from the provided "
    "breakdown JSON. Use € symbol. Hedge with 'context' when appropriate." * 4
)

# Split prompts for parallel text + counter narration (R4 fix BUG-1).
SYSTEM_SONNET_TEXT = (
    "You are Volta, an energy trader's copilot at Volue. " * 4
    + "TIGHT FORMAT: EXACTLY 2 short sentences. NEVER more.\n"
    "Use ONLY numbers from the breakdown. Cite ONCE inline as "
    "(`source_curve`, YYYY-MM-DDTHH:MM CET). Use € symbol. Never invent.\n"
    "If German question, answer in German. If English, English.\n"
    "Sentence 1 = the answer. Sentence 2 = one actionable phrase tied to data."
) * 2

SYSTEM_SONNET_COUNTER = (
    "You are Volta playing devil's advocate. " * 4
    + "TIGHT FORMAT: EXACTLY 2 short sentences. NEVER more.\n"
    "Start with 'However,' or 'Caveat:'. Cite the counter-evidence by "
    "source_curve+value ONCE. Never invent numbers.\n"
    "End with: 'Treat as context, not proof.'\n"
    "If German question, German answer."
) * 2

NARRATION_TIMEOUT_S = 8.0
# UC2's first call writes the cache block; allow more headroom so the live
# narration usually wins over the deterministic fallback.
UC2_NARRATION_TIMEOUT_S = 15.0

TOOLS = [
    {
        "name": "apply_layout",
        "description": (
            "Apply the predefined layout for a known thesis. Fast path. "
            "Choose thesis_key from the closed enum."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "thesis_key": {
                    "type": "string",
                    "enum": list(THESIS_KEYS),
                    "description": (
                        "Closed enum. Pick a baked key only when there's a clear "
                        "semantic match; otherwise pick 'ad_hoc' as catch-all."
                    ),
                },
                "theme": {"type": "string"},
            },
            "required": ["thesis_key", "theme"],
        },
    }
]

# Stop conditions (phase1/01 §2.6)
TIMEOUT_TOTAL_S = 8.0
TIMEOUT_NARRATION_S = 4.0
MAX_TIER2_ITERATIONS = 5


@dataclass
class IntentPayload:
    text: Optional[str] = None
    news_id: Optional[str] = None
    canvas_state: dict = field(default_factory=dict)
    mode: Optional[str] = None  # "create" | "edit" | "explain" | None (auto)


def parse_intent(payload: dict) -> IntentPayload:
    return IntentPayload(
        text=payload.get("text"),
        news_id=payload.get("news_id"),
        canvas_state=payload.get("canvas_state", {}) or {},
        mode=payload.get("mode"),
    )


def classify_with_regex(text: str) -> Optional[str]:
    """Defensive R3 fallback — returns the first thesis_key whose pattern matches."""
    if not text:
        return None
    for k, pat in THESIS_PATTERNS.items():
        if pat.search(text):
            return k
    return None


def _heuristic_thesis_from_text(text: str) -> Optional[str]:
    """Lightweight keyword sniff used to pick a Haiku fixture in REPLAY mode."""
    lowered = text.lower()
    for k in BAKED_THESIS_KEYS:
        # split off the leading area-prefix so we match against "duck_curve",
        # "price_crash", "se4_spread".
        suffix = k.split("_", 1)[1].replace("_", " ")
        if suffix in lowered:
            return k
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def handle_intent(
    intent_id: str,
    payload: dict,
    *,
    manager,
    clock,
    news_engine=None,
) -> None:
    """Route UC1/UC2 and emit all WS ops + always emit done at the end."""
    req = parse_intent(payload)
    start = time.perf_counter()
    try:
        if req.news_id:
            await _handle_news_click(
                intent_id, req, manager=manager, clock=clock, news_engine=news_engine
            )
        else:
            await _handle_thesis(intent_id, req, manager=manager, clock=clock, news_engine=news_engine)
    except Exception as exc:  # noqa: BLE001 — orchestrator must never crash the loop
        log.exception("orchestrator error for %s", intent_id)
        await manager.emit(
            "error",
            {
                "code": "ORCHESTRATOR_ERROR",
                "message": f"{type(exc).__name__}: {exc}",
                "intent_id": intent_id,
                "fatal": False,
            },
        )
    finally:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        await manager.emit(
            "done", {"intent_id": intent_id, "elapsed_ms": elapsed_ms}
        )


# ---------------------------------------------------------------------------
# UC1 — text thesis
# ---------------------------------------------------------------------------


async def _handle_thesis(intent_id: str, req: IntentPayload, *, manager, clock, news_engine=None) -> None:
    import os

    from backend.layouts import LAYOUTS, get_intent_recommendation, resolve
    from backend.llm import chat

    text = (req.text or "").strip()
    if not text:
        await manager.emit(
            "error",
            {
                "code": "EMPTY_INTENT",
                "message": "empty text and no news_id",
                "intent_id": intent_id,
                "fatal": False,
            },
        )
        return

    # === LIVE MODE: 3-mode dispatch (create / edit / explain) ===
    if os.environ.get("LIVE_VOLUE", "1") == "1":
        canvas_state = req.canvas_state or {}
        canvas_themes = canvas_state.get("themes") if isinstance(canvas_state, dict) else None
        is_filled = isinstance(canvas_themes, list) and bool(canvas_themes)

        # Explicit mode from frontend > implicit (empty canvas → create).
        mode = (req.mode or "").lower().strip() or None
        if mode not in ("create", "edit", "explain"):
            mode = None
        if mode is None:
            mode = "edit" if is_filled else "create"
        if not is_filled and mode in ("edit", "explain"):
            # No canvas to edit/explain against — fall back to create.
            mode = "create"

        if mode == "create":
            if is_filled:
                await manager.emit("clear_canvas", {"reason": "create_mode"})
            await _handle_thesis_composed(
                intent_id, text, manager=manager, clock=clock, news_engine=news_engine
            )
        elif mode == "edit":
            await _handle_edit(
                intent_id, text, canvas_state,
                manager=manager, clock=clock, news_engine=news_engine,
            )
        else:  # explain
            await _handle_explain(
                intent_id, text, canvas_state,
                manager=manager, clock=clock, news_engine=news_engine,
            )
        return

    # === LEGACY MODE (tests): regex/Haiku → fixed LAYOUTS bundle ===
    await manager.emit("clear_canvas", {"reason": "new_intent"})

    # 0. Auto-advance virtual_now to end of demo day so the replay-mask
    #    exposes the full Apr-5 day to chart consumers. Without this the
    #    cache is masked at 00:00 UTC and a chart shows a single point.
    end_of_demo_day = datetime(
        DEFAULT_DEMO_DAY.year,
        DEFAULT_DEMO_DAY.month,
        DEFAULT_DEMO_DAY.day,
        23, 45,
        tzinfo=timezone.utc,
    )
    if clock.now() < end_of_demo_day:
        delta_seconds = (end_of_demo_day - clock.now()).total_seconds()
        ticks = max(1, int(delta_seconds // (TICK_MINUTES * 60)))
        clock.tick(ticks)
        await manager.emit(
            "clock_tick",
            {
                "virtual_now": clock.now().isoformat(),
                "tick_count": clock.tick_count,
                "fired_news_ids": [],
            },
        )

    # 1. Audit log — 6-step observable reasoning. Step 1: intake.
    preview = text[:72] + ("…" if len(text) > 72 else "")
    await manager.emit(
        "tool_call",
        {
            "stage": "intake",
            "message": f"Reading: “{preview}”",
            "intent_id": intent_id,
        },
    )
    await asyncio.sleep(0.12)

    # Step 2: classify (regex or Haiku) — emit BEFORE running it so the user
    # sees which path we are taking and (if Haiku) the model name.
    thesis_key: Optional[str] = classify_with_regex(text)
    haiku_fixture: Optional[str] = (
        f"haiku__apply_layout__{thesis_key}__v1" if thesis_key else None
    )
    if thesis_key is not None:
        matched = THESIS_PATTERNS[thesis_key].pattern[:50] + "…"
        classify_msg = f"Regex match ▸ {thesis_key}  (pattern: {matched})"
    else:
        classify_msg = "No regex match — Haiku classifier (claude-haiku-4-5)…"
    await manager.emit(
        "tool_call",
        {"stage": "classify", "message": classify_msg, "intent_id": intent_id},
    )
    await asyncio.sleep(0.12)

    # 2. If regex missed, try Haiku — pick a fixture deterministically so the
    #    REPLAY-mode also has a deterministic answer in the demo. Catch-all
    #    falls through to 'ad_hoc' (synthesized layout) when no keyword fits.
    if thesis_key is None:
        guess = _heuristic_thesis_from_text(text) or "ad_hoc"
        haiku_fixture = (
            f"haiku__apply_layout__{guess}__v1" if guess in BAKED_THESIS_KEYS else None
        )
        thesis_key = guess  # default; may be overridden by the Haiku tool call

        try:
            r = await asyncio.wait_for(
                chat(
                    model="claude-haiku-4-5",
                    system=SYSTEM_HAIKU,
                    messages=[{"role": "user", "content": text}],
                    tools=TOOLS,
                    tool_choice={
                        "type": "tool",
                        "name": "apply_layout",
                        "disable_parallel_tool_use": True,
                    },
                    max_tokens=256,
                    fixture_key=haiku_fixture,
                ),
                timeout=TIMEOUT_TOTAL_S,
            )
            for blk in r.content:
                if (
                    getattr(blk, "type", None) == "tool_use"
                    and getattr(blk, "name", None) == "apply_layout"
                ):
                    tk = blk.input.get("thesis_key")
                    if tk in THESIS_KEYS:
                        thesis_key = tk
                    break
        except (asyncio.TimeoutError, FileNotFoundError) as exc:
            log.info(
                "haiku unavailable for %s (%s) — using heuristic %s",
                intent_id, type(exc).__name__, thesis_key,
            )
        except Exception as exc:  # noqa: BLE001 — never abort UC1 on an LLM hiccup
            log.warning(
                "haiku call failed for %s: %s — using heuristic %s",
                intent_id, exc, thesis_key,
            )

    if thesis_key not in LAYOUTS:
        await manager.emit(
            "error",
            {
                "code": "LAYOUT_NOT_FOUND",
                "message": f"unknown thesis_key {thesis_key!r}",
                "intent_id": intent_id,
                "fatal": False,
            },
        )
        return

    # Step 3: classify_done — confirm thesis_key + layout bundle label.
    bundle_label = LAYOUTS[thesis_key].theme_label if thesis_key in LAYOUTS else thesis_key
    await manager.emit(
        "tool_call",
        {
            "stage": "classify_done",
            "message": f"thesis_key ▸ {thesis_key}  •  layout: {bundle_label}",
            "intent_id": intent_id,
        },
    )
    await asyncio.sleep(0.12)

    bundle = LAYOUTS[thesis_key]
    windows = resolve(thesis_key, clock)

    # Step 4: resolve — surface how many curves and counter-claims got hydrated.
    total_curves = sum(len(w.curve_keys) for w in windows)
    counter_w_local = next((w for w in windows if w.window_type == "counter"), None)
    points_count = (
        len(counter_w_local.spec.get("points", [])) if counter_w_local else 0
    )
    await manager.emit(
        "tool_call",
        {
            "stage": "resolve",
            "message": (
                f"Hydrating {len(windows)} windows from Volue cache • "
                f"{total_curves} curves • {points_count} counter-claims"
            ),
            "intent_id": intent_id,
        },
    )
    await asyncio.sleep(0.12)

    # 3. Emit ordered canvas ops: spawn_theme → spawn_window × N → intent_recommendation
    theme_id = (
        windows[0].theme_id
        if windows
        else f"theme_{thesis_key}_{uuid.uuid4().hex[:8]}"
    )
    # Personalize the theme label with the trader's words ("your words land").
    label_preview = text[:48] + ("…" if len(text) > 48 else "")
    await manager.emit(
        "spawn_theme",
        {
            "theme_id": theme_id,
            "label": f"“{label_preview}”  —  {bundle.theme_label}",
            "thesis_key": thesis_key,
            "window_order": [w.window_id for w in windows],
            "intent_id": intent_id,
        },
    )
    for w in windows:
        await manager.emit("spawn_window", {**asdict(w), "intent_id": intent_id})
        # Stagger window spawns so the UI sees them appear one-by-one.
        await asyncio.sleep(0.12)

    await manager.emit(
        "intent_recommendation",
        {
            "text": get_intent_recommendation(thesis_key),
            "action": {"type": "apply_layout", "thesis_key": thesis_key},
            "intent_id": intent_id,
        },
    )

    # Step 5: narrate — Sonnet primary + counter in parallel (fire-and-forget).
    await manager.emit(
        "tool_call",
        {
            "stage": "narrate",
            "message": "Sonnet ▸ writing primary + counter (parallel, ~2s)…",
            "intent_id": intent_id,
        },
    )
    asyncio.create_task(
        _narrate_async(
            intent_id, thesis_key, text, windows, manager=manager, clock=clock
        )
    )
    # Step 6 (narrate_done) is emitted from inside _narrate_async.


async def _handle_thesis_composed(
    intent_id: str,
    text: str,
    *,
    manager,
    clock,
    news_engine=None,
) -> None:
    """Live AI-composer dispatch — Sonnet picks 3-4 windows from the live catalog.

    UX: spawn 4 skeleton cards IMMEDIATELY so the canvas is non-empty during
    the ~15s composer call, then swap each skeleton with the real composition.
    """
    from backend import composer

    preview = text[:72] + ("…" if len(text) > 72 else "")
    await manager.emit(
        "tool_call",
        {"stage": "intake", "message": f"Reading: “{preview}”", "intent_id": intent_id},
    )

    # ---- 1. Skeleton scaffold (instant) ----
    label_preview = text[:48] + ("…" if len(text) > 48 else "")
    skel_theme_id = f"theme_skel_{uuid.uuid4().hex[:8]}"
    skel_types = ["chart", "chart", "text", "counter"]
    skel_ids = [f"skel_{i}_{uuid.uuid4().hex[:6]}" for i in range(4)]
    await manager.emit(
        "spawn_theme",
        {
            "theme_id": skel_theme_id,
            "label": f"“{label_preview}”  —  composing…",
            "thesis_key": None,
            "window_order": skel_ids,
            "intent_id": intent_id,
        },
    )
    for sid, st in zip(skel_ids, skel_types):
        spec = (
            {
                "chart_type": "line", "x_key": "ts", "y_key": "value",
                "y_unit": "—", "t_from": clock.iso(), "t_to": clock.iso(),
                "annotations": [],
            } if st == "chart" else
            {"body": "", "badge": None, "dismissable": True, "sources": []} if st == "text" else
            {"body": "", "badge": "counter_evidence", "dismissable": True, "points": []}
        )
        await manager.emit(
            "spawn_window",
            {
                "window_id": sid,
                "theme_id": skel_theme_id,
                "window_type": st,
                "title": "Composing…",
                "summary_line": "Volta is painting this card",
                "state": "small",
                "curve_keys": [],
                "spec": spec,
                "grounding": None,
                "raw_toggle": False,
                "intent_id": intent_id,
            },
        )

    regex_hint = classify_with_regex(text)
    await manager.emit(
        "tool_call",
        {
            "stage": "compose",
            "message": (
                "Sonnet ▸ composing layout"
                + (f" · regex hint: {regex_hint}" if regex_hint else "")
                + "…"
            ),
            "intent_id": intent_id,
        },
    )

    layout = await composer.compose(
        text, clock=clock, news_engine=news_engine, thesis_hint=regex_hint
    )
    theme_id, windows = composer.to_windows(layout, clock)

    # Force composed windows into the skeleton theme so the swap is in-place.
    for w in windows:
        w.theme_id = skel_theme_id
    theme_id = skel_theme_id

    total_curves = sum(len(w.curve_keys) for w in windows)
    counter_w = next((w for w in windows if w.window_type == "counter"), None)
    points_count = len(counter_w.spec.get("points", [])) if counter_w else 0
    await manager.emit(
        "tool_call",
        {
            "stage": "resolve",
            "message": (
                f"Composed {len(windows)} windows • {total_curves} live curves • "
                f"{points_count} counter-claims hydrated from cache"
            ),
            "intent_id": intent_id,
        },
    )

    theme_label = layout.get("theme_label") or "Composed canvas"
    label_preview = text[:48] + ("…" if len(text) > 48 else "")
    await manager.emit(
        "spawn_theme",
        {
            "theme_id": theme_id,
            "label": f"“{label_preview}”  —  {theme_label}",
            "thesis_key": regex_hint,
            "window_order": [w.window_id for w in windows],
            "intent_id": intent_id,
        },
    )
    for w in windows:
        # Re-stamp theme_id from composer.to_windows in case it changed
        w.theme_id = theme_id
        await manager.emit("spawn_window", {**asdict(w), "intent_id": intent_id})
        await asyncio.sleep(0.1)

    recommendation = layout.get("intent_recommendation") or (
        "Here’s your composed canvas — ask follow-ups or use the lupe icon on any card."
    )
    await manager.emit(
        "intent_recommendation",
        {
            "text": recommendation,
            "action": {
                "type": "compose_layout",
                "thesis_hint": regex_hint,
                "rationale": layout.get("rationale_short", ""),
            },
            "intent_id": intent_id,
        },
    )

    await manager.emit(
        "tool_call",
        {
            "stage": "narrate",
            "message": "Sonnet ▸ writing primary + counter (parallel)…",
            "intent_id": intent_id,
        },
    )
    # Reuse _narrate_async with regex_hint as thesis_key (falls back to ad_hoc internally)
    asyncio.create_task(
        _narrate_async(
            intent_id,
            regex_hint or "ad_hoc",
            text,
            windows,
            manager=manager,
            clock=clock,
        )
    )


SYSTEM_EXPLAIN = (
    "You are Volta — explain mode. The trader asks a question about an "
    "existing canvas. " * 3
    + "You DO NOT modify the canvas. You write a tight markdown answer that:\n"
    "- ≤4 sentences total\n"
    "- Cites the curves on the canvas where relevant (use backticks: `pri_de_spot_h`)\n"
    "- Pulls one or two specific values from the catalog summary if useful\n"
    "- Ends with one actionable phrase (e.g. 'Watch the residual load after 16:00 CET.')\n"
    "- German question → German answer.\n"
    "Format with **bold** for the key numbers and one `code` for the primary curve."
) * 2


async def _handle_explain(
    intent_id: str,
    text: str,
    canvas_state: dict,
    *,
    manager,
    clock,
    news_engine=None,
) -> None:
    """Explain mode: stream a single answer card into the existing canvas."""
    from backend import composer
    from backend.llm import chat_stream

    preview = text[:72] + ("…" if len(text) > 72 else "")
    await manager.emit(
        "tool_call",
        {"stage": "intake", "message": f"Explain: “{preview}”", "intent_id": intent_id},
    )

    canvas_summary = composer.summarize_canvas_for_prompt(canvas_state)
    catalog = composer.build_catalog_block(max_lines=20)

    # Land the explain card in the first existing theme so it sits next to the
    # context it explains.
    themes = canvas_state.get("themes") if isinstance(canvas_state, dict) else None
    theme_id = None
    if isinstance(themes, list) and themes and isinstance(themes[0], dict):
        theme_id = themes[0].get("theme_id")
    if not theme_id:
        theme_id = f"theme_explain_{uuid.uuid4().hex[:6]}"

    explain_window_id = f"win_explain_{uuid.uuid4().hex[:8]}"
    await manager.emit(
        "spawn_window",
        {
            "window_id": explain_window_id,
            "theme_id": theme_id,
            "window_type": "text",
            "title": f"💬 {preview[:48]}",
            "summary_line": "Volta explains — live stream",
            "state": "small",
            "curve_keys": [],
            "spec": {"body": "", "badge": None, "dismissable": True, "sources": []},
            "grounding": None,
            "raw_toggle": False,
            "intent_id": intent_id,
        },
    )

    await manager.emit(
        "tool_call",
        {"stage": "explain", "message": "Sonnet ▸ streaming answer…", "intent_id": intent_id},
    )

    user_prompt = (
        f"{catalog}\n\n"
        f"virtual_now: {clock.iso()}\n\n"
        f"Current canvas:\n{canvas_summary}\n\n"
        f'Trader question (explain only — do NOT change the canvas):\n"{text}"\n\n'
        "Write a ≤4-sentence answer in markdown."
    )

    async def on_text(full: str) -> None:
        await manager.emit(
            "update_window",
            {
                "window_id": explain_window_id,
                "patch": {"body": full},
                "intent_id": intent_id,
            },
        )

    await chat_stream(
        model="claude-sonnet-4-6",
        system=SYSTEM_EXPLAIN,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=400,
        on_text=on_text,
    )


async def _handle_edit(
    intent_id: str,
    text: str,
    canvas_state: dict,
    *,
    manager,
    clock,
    news_engine=None,
) -> None:
    """NL-driven edit — Sonnet emits remove/swap/add/reorder ops. Mode is
    explicit from the frontend; the canvas is preserved.
    """
    from backend import composer

    preview = text[:72] + ("…" if len(text) > 72 else "")
    await manager.emit(
        "tool_call",
        {"stage": "intake", "message": f"Edit: “{preview}”", "intent_id": intent_id},
    )
    await manager.emit(
        "tool_call",
        {"stage": "edit", "message": "Sonnet ▸ planning edit ops…", "intent_id": intent_id},
    )

    edit_input = await composer.edit(text, canvas_state, clock=clock, news_engine=news_engine)
    ops = composer.materialize_edit_ops(edit_input, canvas_state, clock=clock, intent_id=intent_id)

    if not ops:
        await manager.emit(
            "tool_call",
            {
                "stage": "edit",
                "message": "Edit had no valid ops — try rephrasing (e.g. 'swap the news card for a wind chart').",
                "intent_id": intent_id,
            },
        )
        return

    await manager.emit(
        "tool_call",
        {
            "stage": "edit",
            "message": f"Applying {len(ops)} op(s): {', '.join(op['op'] for op in ops)}",
            "intent_id": intent_id,
        },
    )

    # Emit each op + collect any new text/counter windows for fire-and-forget narration
    new_text_counter: list = []
    for op in ops:
        await manager.emit(op["op"], op["payload"])
        await asyncio.sleep(0.06)
        payload = op["payload"]
        new_w = payload.get("new_window") if op["op"] == "swap_window" else (payload if op["op"] == "spawn_window" else None)
        if new_w and new_w.get("window_type") in ("text", "counter"):
            from backend.models import Window
            new_text_counter.append(
                Window(
                    window_id=new_w["window_id"],
                    theme_id=new_w["theme_id"],
                    window_type=new_w["window_type"],
                    title=new_w["title"],
                    summary_line=new_w["summary_line"],
                    state="small",
                    curve_keys=new_w.get("curve_keys", []),
                    spec=new_w["spec"],
                    grounding=None,
                    raw_toggle=True,
                )
            )

    if new_text_counter:
        asyncio.create_task(
            _narrate_async(
                intent_id, "ad_hoc", text, new_text_counter, manager=manager, clock=clock
            )
        )


async def _narrate_async(
    intent_id: str,
    thesis_key: str,
    user_text: str,
    windows,
    *,
    manager,
    clock,
) -> None:
    """Tier-3 Sonnet narration. Split: primary (text window) + counter (counter window)
    run in PARALLEL with different system prompts. Falls back to fixture for text and
    deterministic method_note for counter when live calls fail / no API key.
    """
    from backend.llm import chat

    try:
        bk = None
        if PRECOMPUTED_PATH.exists():
            payload = json.loads(PRECOMPUTED_PATH.read_text(encoding="utf-8"))
            # Support both shapes: {"thesis_keys": {...}} and flat {thesis_key: {...}}.
            bks = payload.get("thesis_keys", payload)
            bk = bks.get(thesis_key) if isinstance(bks, dict) else None
        # ad_hoc has no precomputed breakdown — synthesize a minimal payload so
        # Sonnet still gets a structured prompt and can answer the free-form
        # question using the trader's words.
        if bk is None and thesis_key == "ad_hoc":
            bk = {
                "headline": "Ad-hoc question — no baked thesis matched",
                "method_note": (
                    "No precomputed breakdown for this question. Answer using "
                    "general DE market context (spot price, NL/BE cross-border, "
                    "CO2 EUA) and acknowledge any gaps; treat as context, not proof."
                ),
                "drivers": [],
                "user_question": user_text,
            }
        if bk is None:
            return

        text_win = next((w for w in windows if w.window_type == "text"), None)
        counter_win = next((w for w in windows if w.window_type == "counter"), None)
        hydrated_points = (counter_win.spec.get("points") if counter_win else []) or []

        # Fixture fallback names — existing fixture for text path; counter is live-only.
        # ad_hoc has no baked fixture (live-only), so omit fixture_key entirely.
        fx_text = (
            f"sonnet__narration__{thesis_key}_breakdown__v1"
            if thesis_key in BAKED_THESIS_KEYS
            else None
        )

        text_prompt = (
            f"Trader's question:\n{user_text!r}\n\n"
            f"Fundamental breakdown (from Volue cache):\n"
            f"{json.dumps(bk, ensure_ascii=False, indent=2)}\n\n"
            f"Write the primary narration."
        )
        counter_prompt = (
            f"Trader's question:\n{user_text!r}\n\n"
            f"Primary breakdown:\n{json.dumps(bk, ensure_ascii=False, indent=2)}\n\n"
            f"Counter-evidence (hydrated from cache):\n"
            f"{json.dumps(hydrated_points, ensure_ascii=False, indent=2)}\n\n"
            f"Write the counter-narrative."
        )

        async def _call_text():
            try:
                return await chat(
                    model="claude-sonnet-4-6",
                    system=SYSTEM_SONNET_TEXT,
                    messages=[{"role": "user", "content": text_prompt}],
                    max_tokens=220,
                    fixture_key=fx_text,
                    force_live=True,
                )
            except Exception as exc:  # noqa: BLE001 — narration is best-effort
                log.warning("text narration failed: %s", exc)
                return None

        async def _call_counter():
            try:
                return await chat(
                    model="claude-sonnet-4-6",
                    system=SYSTEM_SONNET_COUNTER,
                    messages=[{"role": "user", "content": counter_prompt}],
                    max_tokens=220,
                    fixture_key=None,  # no counter fixture; live only
                    force_live=True,
                )
            except Exception as exc:  # noqa: BLE001 — narration is best-effort
                log.warning("counter narration failed: %s", exc)
                return None

        # Parallel — total latency = max(text, counter).
        text_r, counter_r = await asyncio.wait_for(
            asyncio.gather(_call_text(), _call_counter()),
            timeout=NARRATION_TIMEOUT_S,
        )

        def _extract(r) -> str:
            if r is None:
                return ""
            for blk in r.content:
                if getattr(blk, "type", None) == "text":
                    return blk.text or ""
            return ""

        primary_text = _extract(text_r)
        counter_text = _extract(counter_r)

        # Deterministic counter fallback if Sonnet failed: use method_note +
        # the 2 lowest-listed drivers from the breakdown.
        if not counter_text:
            drivers = bk.get("drivers", []) or []
            method_note = bk.get("method_note", "") or ""
            extra = drivers[-2:] if len(drivers) >= 2 else drivers
            extra_str = "; ".join(
                f"{d.get('label', '?')}: {d.get('value', '?')} {d.get('unit', '')}".strip()
                for d in extra
            )
            counter_text = (
                f"{method_note}\n\n"
                f"The thesis above does not foreground: {extra_str}. "
                f"Treat as context, not proof."
            ).strip()

        # Step 6: narrate_done — final audit-log line.
        await manager.emit(
            "tool_call",
            {
                "stage": "narrate_done",
                "message": (
                    f"Sonnet ▸ {len(primary_text)} chars primary, "
                    f"{len(counter_text)} chars counter"
                ),
                "intent_id": intent_id,
            },
        )

        # Patch text window — TEXT ONLY (no longer mirrored into counter).
        if text_win and primary_text:
            await manager.emit(
                "update_window",
                {
                    "window_id": text_win.window_id,
                    "patch": {"body": primary_text},
                    "intent_id": intent_id,
                },
            )
        # Patch counter window — SEPARATE narration.
        if counter_win and counter_text:
            await manager.emit(
                "update_window",
                {
                    "window_id": counter_win.window_id,
                    "patch": {"body": counter_text},
                    "intent_id": intent_id,
                },
            )
    except Exception as exc:  # noqa: BLE001 — narration is best-effort
        log.debug("narration failed for %s: %s", intent_id, exc)


# ---------------------------------------------------------------------------
# UC2 — news_id click
# ---------------------------------------------------------------------------

# Sonnet system prompt for UC2 — live narration of the news event in market
# context. Padded for prompt-caching (≥1024 tokens for Sonnet caching).
SYSTEM_SONNET_UC2 = (
    "You are Volta, an energy trader's copilot at Volue. " * 4
    + "A trader has clicked on a derived-news event from the ticker. They want "
    "to understand what it means for the German power market RIGHT NOW.\n\n"
    "You receive: (1) the news event itself (headline, severity, source_curve, "
    "delta_value, hedged_text), (2) a fundamental breakdown JSON from the Volue "
    "Insight cache for the demo day.\n\n"
    "Write 2-3 sentences that explain what the trader is seeing. "
    "Cite every number inline with source_curve and ts in parentheses, e.g. "
    "(`pri de spot eur/mwh cet h a`, 2026-04-05T12:00 CET). "
    "Use € symbol. NEVER invent numbers — only reuse values from the breakdown "
    "or the news event. NEVER cite a curve not in the provided JSON. "
    "If the news event is a forecast revision, explain the directional change "
    "and what it implies for residual demand (con - spv - wnd). "
    "If a price spike, link it to the underlying supply/demand drivers. "
    "If an Optimeering imbalance range, frame it as uncertainty in the band. "
    "End with one short sentence the trader can act on. "
    "Hedge with 'context, not proof' once when appropriate."
) * 2


def _news_id_to_curve(nid: str) -> str:
    """Map a news_id to the primary curve_key shown on the UC2 chart window."""
    if not nid:
        return "pri_de_spot_h"
    n = nid.lower()
    if n.startswith("forecast_revision_pro_de_wnd"):
        return "pro_de_wnd_ec00_f"
    if n.startswith("forecast_revision_pro_de_spv"):
        return "pro_de_spv_ec00_f"
    if n.startswith("price_") and "pri_de_spot" in n:
        return "pri_de_spot_h"
    if n.startswith("optimeering_range_"):
        return n[len("optimeering_range_"):]
    return "pri_de_spot_h"


def _news_id_to_thesis(nid: str) -> str:
    """Pick the thesis_key whose precomputed breakdown best frames this event."""
    if not nid:
        return "de_price_crash"
    n = nid.lower()
    if n.startswith("optimeering_range_") or "se4" in n or "dk1" in n or "no1" in n:
        return "dk1_se4_spread"
    if "spv" in n:
        return "de_duck_curve"
    return "de_price_crash"


def _resolve_news_event(nid: str, *, news_engine, clock) -> dict:
    """Recover a DerivedNewsEvent-shaped dict for a news_id.

    First tries `news_engine.events_at(now)` (cheap if not in cooldown); falls
    back to a synthetic event so the news card always has a headline + body.
    """
    if news_engine is not None:
        try:
            evts = news_engine.events_at(clock.now())
            for ev in evts:
                if getattr(ev, "news_id", None) == nid:
                    from dataclasses import asdict as _asdict
                    return _asdict(ev)
        except Exception as exc:  # noqa: BLE001
            log.debug("UC2 news_engine.events_at failed: %s", exc)

    n = (nid or "").lower()
    if n.startswith("forecast_revision_pro_de_wnd"):
        return {
            "news_id": nid, "area": "DE", "severity": "med",
            "headline": "DE wind forecast revised — context, not proof",
            "delta_value": 0.0, "unit": "MWh",
            "source_curve": "pro de wnd ec00 mwh/h cet min15 f",
            "ts": clock.now().isoformat(), "hedged": True,
            "hedged_text": (
                "Forecast revision detected — context, not proof; "
                "could reflect a changed weather model."
            ),
        }
    if n.startswith("forecast_revision_pro_de_spv"):
        return {
            "news_id": nid, "area": "DE", "severity": "med",
            "headline": "DE solar forecast revised — context, not proof",
            "delta_value": 0.0, "unit": "MWh",
            "source_curve": "pro de spv ec00 mwh/h cet min15 f",
            "ts": clock.now().isoformat(), "hedged": True,
            "hedged_text": (
                "Forecast revision detected — context, not proof; "
                "could reflect a changed weather model."
            ),
        }
    if n.startswith("price_") and "pri_de_spot" in n:
        return {
            "news_id": nid, "area": "DE", "severity": "high",
            "headline": "DE spot price movement — context, not proof",
            "delta_value": 0.0, "unit": "EUR/MWh",
            "source_curve": "pri_de_spot_h",
            "ts": clock.now().isoformat(), "hedged": True,
            "hedged_text": (
                "Price movement detected — context, not proof; "
                "could reflect short-term sentiment."
            ),
        }
    if n.startswith("optimeering_range_"):
        series = n[len("optimeering_range_"):]
        return {
            "news_id": nid,
            "area": "NO1" if "no1" in series else ("DK1" if "dk1" in series else "SE4"),
            "severity": "med",
            "headline": f"Imbalance quantile spread widened — {series}",
            "delta_value": 0.0, "unit": "MWh",
            "source_curve": series,
            "ts": clock.now().isoformat(), "hedged": True,
            "hedged_text": (
                "Optimeering quantile spread widened — context, not proof; "
                "could reflect uncertainty."
            ),
        }
    return {
        "news_id": nid, "area": "DE", "severity": "low",
        "headline": f"Event {nid}", "delta_value": 0.0, "unit": "",
        "source_curve": "", "ts": clock.now().isoformat(), "hedged": True,
        "hedged_text": "Context, not proof — derived from cached data.",
    }


# Counter-evidence claim templates per region. Re-using the layouts shape so
# `_hydrate_counter_points` fills `value`+`ts` from the cache for the demo day.
_UC2_CLAIMS_DE = [
    {"claim": "DE consumption (daily avg)", "unit": "MWh/h",
     "source_curve": "con de mwh/h cet min15 a"},
    {"claim": "NL spot price (daily avg)", "unit": "€/MWh",
     "source_curve": "pri nl spot €/mwh cet h a"},
    {"claim": "BE spot price (daily avg)", "unit": "€/MWh",
     "source_curve": "pri be spot €/mwh cet h a"},
]
_UC2_CLAIMS_NORDIC = [
    {"claim": "NO1 Imbalance Point", "unit": "MWh",
     "source_curve": "optimeering NO1 Imbalance Point"},
    {"claim": "DK1 Imbalance Point", "unit": "MWh",
     "source_curve": "optimeering DK1 Imbalance Point"},
    {"claim": "SE4 Imbalance Point", "unit": "MWh",
     "source_curve": "optimeering SE4 Imbalance Point"},
]


async def _handle_news_click(
    intent_id: str, req: IntentPayload, *, manager, clock, news_engine=None
) -> None:
    """news_id → 4 windows (chart + text + counter + news) with live Sonnet narration.

    Mirrors UC1's shape so the user gets the same fundamental-breakdown lens
    when investigating a news event, with the curve relevant to the news_id on
    the chart and a Sonnet-written explanation of what the event means today.
    """
    from backend.layouts import _hydrate_counter_points
    from backend.fundamentals import decompose

    # Each news-click replaces the canvas with the focused context.
    await manager.emit("clear_canvas", {"reason": "news_click"})

    nid = req.news_id or "unknown"

    # 1. Resolve mappings.
    curve_key = _news_id_to_curve(nid)
    thesis_key = _news_id_to_thesis(nid)
    news_event = _resolve_news_event(nid, news_engine=news_engine, clock=clock)
    area = news_event.get("area", "DE") or "DE"

    # 2. Fundamental breakdown for the news event's area + matching focus.
    focus = {
        "de_price_crash": "price_crash",
        "de_duck_curve": "duck_curve",
        "dk1_se4_spread": "spread",
    }.get(thesis_key, "price_crash")
    t_from = clock.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    t_to = clock.now().replace(hour=23, minute=45, second=0, microsecond=0).isoformat()
    bk_data: dict | None = None
    try:
        bk = decompose(area, t_from, t_to, focus, clock)
        from dataclasses import asdict as _asdict
        bk_data = _asdict(bk)
    except Exception as exc:  # noqa: BLE001 — fall back to the precomputed file
        log.debug("UC2 decompose failed: %s", exc)
    if bk_data is None:
        try:
            if PRECOMPUTED_PATH.exists():
                payload = json.loads(PRECOMPUTED_PATH.read_text(encoding="utf-8"))
                bks = payload.get("thesis_keys", payload)
                if isinstance(bks, dict):
                    bk_data = bks.get(thesis_key) or bks.get("de_price_crash")
        except Exception as exc:  # noqa: BLE001
            log.debug("UC2 precomputed fallback failed: %s", exc)

    # 3. Hydrated counter-evidence claims.
    claim_template = (
        _UC2_CLAIMS_NORDIC if thesis_key == "dk1_se4_spread" else _UC2_CLAIMS_DE
    )
    try:
        hydrated_points = _hydrate_counter_points(list(claim_template), clock)
    except Exception as exc:  # noqa: BLE001
        log.debug("UC2 hydrate counter failed: %s", exc)
        hydrated_points = list(claim_template)

    # 4. Window ids + theme.
    theme_id = f"theme_uc2_{nid}_{uuid.uuid4().hex[:6]}"
    chart_win_id = f"win_uc2_{nid}_chart"
    text_win_id = f"win_uc2_{nid}_text"
    counter_win_id = f"win_uc2_{nid}_counter"
    news_win_id = f"win_uc2_{nid}_news"

    await manager.emit(
        "spawn_theme",
        {
            "theme_id": theme_id,
            "label": f"News context: {nid}",
            "thesis_key": None,
            "window_order": [chart_win_id, text_win_id, counter_win_id, news_win_id],
            "intent_id": intent_id,
        },
    )

    # 5. Chart window — the curve referenced by this news_id.
    chart_y_unit = (
        "MWh/h"
        if curve_key.startswith(("pro_", "con_")) or "imbalance" in curve_key
        else "€/MWh"
    )
    chart_type = "area" if curve_key == "pri_de_spot_h" else "line"
    await manager.emit(
        "spawn_window",
        {
            "window_id": chart_win_id,
            "theme_id": theme_id,
            "window_type": "chart",
            "title": news_event.get("headline", "") or f"Curve {curve_key}",
            "summary_line": "Live curve from Volue cache",
            "state": "small",
            "curve_keys": [curve_key],
            "spec": {
                "chart_type": chart_type,
                "x_key": "ts",
                "y_key": "value",
                "y_unit": chart_y_unit,
                "t_from": t_from,
                "t_to": t_to,
                "annotations": [],
            },
            "grounding": None,
            "raw_toggle": True,
            "intent_id": intent_id,
        },
    )

    # 6. Text window — empty placeholder; Sonnet fills it via update_window.
    await manager.emit(
        "spawn_window",
        {
            "window_id": text_win_id,
            "theme_id": theme_id,
            "window_type": "text",
            "title": "What does this mean for the market?",
            "summary_line": "Live Sonnet narration over the breakdown JSON",
            "state": "small",
            "curve_keys": [],
            "spec": {
                "body": "",
                "badge": "context_not_proof",
                "dismissable": True,
                "sources": [],
            },
            "grounding": None,
            "raw_toggle": True,
            "intent_id": intent_id,
        },
    )

    # 7. Counter window — hydrated claims, no narration text for UC2.
    await manager.emit(
        "spawn_window",
        {
            "window_id": counter_win_id,
            "theme_id": theme_id,
            "window_type": "counter",
            "title": "Counter-Evidence",
            "summary_line": "Cross-checks from cache (context, not proof).",
            "state": "small",
            "curve_keys": [
                p.get("source_curve", "")
                for p in hydrated_points
                if p.get("source_curve")
            ],
            "spec": {
                "body": "",
                "badge": "counter_evidence",
                "dismissable": True,
                "points": hydrated_points,
            },
            "grounding": None,
            "raw_toggle": True,
            "intent_id": intent_id,
        },
    )

    # 8. News window — the actual derived event.
    await manager.emit(
        "spawn_window",
        {
            "window_id": news_win_id,
            "theme_id": theme_id,
            "window_type": "news",
            "title": "Source event",
            "summary_line": news_event.get("hedged_text", "") or f"Event {nid}",
            "state": "small",
            "curve_keys": [],
            "spec": {
                "headline": news_event.get("headline", "") or f"Event {nid}",
                "body": news_event.get("hedged_text", "") or "",
                "badge": "context_not_proof",
                "news_id": nid,
                "severity": news_event.get("severity", "low") or "low",
            },
            "grounding": None,
            "raw_toggle": True,
            "intent_id": intent_id,
        },
    )

    # 9. Fire-and-forget live Sonnet narration over the event + breakdown.
    asyncio.create_task(
        _uc2_narrate_async(
            intent_id,
            news_event=news_event,
            bk_data=bk_data,
            text_win_id=text_win_id,
            manager=manager,
            clock=clock,
        )
    )


async def _uc2_narrate_async(
    intent_id: str,
    *,
    news_event: dict,
    bk_data: dict | None,
    text_win_id: str,
    manager,
    clock,
) -> None:
    """Live Sonnet narration for UC2. Fixture-free per anti-hardcode mandate."""
    from backend.llm import chat

    try:
        virtual_now = clock.now().isoformat()
        headline = news_event.get("headline", "") or "(no headline)"
        user_prompt = (
            f"A trader sees this news event: {headline}. "
            f"What does this mean for the German power market on {virtual_now}? "
            f"Use the fundamental breakdown data below. 2-3 sentences, cite "
            f"source_curve+ts inline, NO invented numbers.\n\n"
            f"News event:\n{json.dumps(news_event, ensure_ascii=False, indent=2)}\n\n"
            f"Fundamental breakdown (Volue cache):\n"
            f"{json.dumps(bk_data or {}, ensure_ascii=False, indent=2)}"
        )

        # Cache the (large, static) system prompt across UC2 calls.
        system_blocks = [
            {
                "type": "text",
                "text": SYSTEM_SONNET_UC2,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        try:
            r = await asyncio.wait_for(
                chat(
                    model="claude-sonnet-4-6",
                    system=system_blocks,
                    messages=[{"role": "user", "content": user_prompt}],
                    max_tokens=400,
                    fixture_key=None,  # UC2 is live-only; adapts to each news_id
                    force_live=True,
                ),
                timeout=UC2_NARRATION_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001 — narration is best-effort
            log.warning(
                "UC2 narration unavailable [%s: %s] — using deterministic fallback",
                type(exc).__name__, exc,
            )
            r = None

        body = ""
        if r is not None:
            for blk in r.content:
                if getattr(blk, "type", None) == "text":
                    body = blk.text or ""
                    break

        if not body:
            drivers = (bk_data or {}).get("drivers", []) if isinstance(bk_data, dict) else []
            top = drivers[:2]
            extra = "; ".join(
                f"{d.get('label', '?')}: {d.get('value', '?')} {d.get('unit', '')}".strip()
                for d in top
            )
            body = (
                f"{news_event.get('hedged_text', 'Context, not proof.')}\n\n"
                f"Cache snapshot: {extra}. Treat as context, not proof."
            ).strip()

        await manager.emit(
            "update_window",
            {
                "window_id": text_win_id,
                "patch": {"body": body},
                "intent_id": intent_id,
            },
        )
    except Exception as exc:  # noqa: BLE001 — narration is best-effort
        log.debug("UC2 narration failed for %s: %s", intent_id, exc)
