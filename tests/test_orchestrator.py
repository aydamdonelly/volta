"""Orchestrator tests — regex classifier + UC1 emission sequence + UC2 fallback.

All LLM calls go through the empty fixtures dir → chat() raises FileNotFoundError,
which the orchestrator must catch silently. We assert on the emitted op sequence.
"""
from __future__ import annotations

import asyncio
import json

import pytest


# ---------------------------------------------------------------------------
# Regex classifier — pure-function tests
# ---------------------------------------------------------------------------


def test_classify_with_regex_duck_curve():
    from backend.orchestrator import classify_with_regex

    assert classify_with_regex("Germany solar duck curve midday") == "de_duck_curve"


def test_classify_with_regex_price_crash():
    from backend.orchestrator import classify_with_regex

    assert classify_with_regex("April 5 negative price crash") == "de_price_crash"


def test_classify_with_regex_dk1_se4():
    from backend.orchestrator import classify_with_regex

    assert classify_with_regex("DK1 to SE4 nordic spread") == "dk1_se4_spread"


def test_classify_with_regex_no_hit():
    from backend.orchestrator import classify_with_regex

    assert classify_with_regex("totally unrelated random text") is None


# ---------------------------------------------------------------------------
# UC1 — full dispatch sequence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_intent_regex_hit_emits_full_sequence(
    demo_clock, monkeypatch, tmp_path
):
    """Empty fixture dir but regex hits → orchestrator emits the full sequence."""
    import backend.llm as L
    import backend.orchestrator as O

    monkeypatch.setattr(L, "FIXTURES_DIR", tmp_path / "fixtures")
    L.reset_budget()

    from backend.ws_manager import ConnectionManager

    mgr = ConnectionManager()
    captured: list[tuple[str, dict]] = []

    async def spy(op, payload):
        captured.append((op, payload))
        return 0

    mgr.emit = spy  # type: ignore[assignment]

    await O.handle_intent(
        "test_intent_1",
        {"text": "I want to trade Germany's solar duck curve"},
        manager=mgr,
        clock=demo_clock,
    )
    # Let any narration task tick (it should noop because no fixture exists).
    await asyncio.sleep(0)

    ops = [op for op, _ in captured]
    assert "clear_canvas" in ops
    assert "spawn_theme" in ops
    assert ops.count("spawn_window") == 4
    assert "intent_recommendation" in ops
    assert "done" in ops
    # done must be last
    assert ops[-1] == "done"


@pytest.mark.asyncio
async def test_handle_intent_routes_to_de_price_crash(
    demo_clock, monkeypatch, tmp_path
):
    import backend.llm as L
    import backend.orchestrator as O

    monkeypatch.setattr(L, "FIXTURES_DIR", tmp_path / "fixtures")
    L.reset_budget()

    from backend.ws_manager import ConnectionManager

    mgr = ConnectionManager()
    captured: list[tuple[str, dict]] = []

    async def spy(op, payload):
        captured.append((op, payload))
        return 0

    mgr.emit = spy  # type: ignore[assignment]

    await O.handle_intent(
        "test_intent_2",
        {"text": "Why did the price crash to negative on April 5?"},
        manager=mgr,
        clock=demo_clock,
    )

    theme = next(p for op, p in captured if op == "spawn_theme")
    assert theme["thesis_key"] == "de_price_crash"


@pytest.mark.asyncio
async def test_handle_intent_routes_to_dk1_se4_spread(
    demo_clock, monkeypatch, tmp_path
):
    import backend.llm as L
    import backend.orchestrator as O

    monkeypatch.setattr(L, "FIXTURES_DIR", tmp_path / "fixtures")
    L.reset_budget()

    from backend.ws_manager import ConnectionManager

    mgr = ConnectionManager()
    captured: list[tuple[str, dict]] = []

    async def spy(op, payload):
        captured.append((op, payload))
        return 0

    mgr.emit = spy  # type: ignore[assignment]

    await O.handle_intent(
        "test_intent_3",
        {"text": "Show me DK1 SE4 spread and nordic imbalance"},
        manager=mgr,
        clock=demo_clock,
    )

    theme = next(p for op, p in captured if op == "spawn_theme")
    assert theme["thesis_key"] == "dk1_se4_spread"


@pytest.mark.asyncio
async def test_handle_intent_emits_done_on_error(demo_clock):
    """Empty body (no text, no news_id) → error op + done."""
    import backend.orchestrator as O
    from backend.ws_manager import ConnectionManager

    mgr = ConnectionManager()
    captured: list[tuple[str, dict]] = []

    async def spy(op, payload):
        captured.append((op, payload))
        return 0

    mgr.emit = spy  # type: ignore[assignment]

    await O.handle_intent("intent_err", {}, manager=mgr, clock=demo_clock)

    ops = [op for op, _ in captured]
    assert "done" in ops
    assert ops[-1] == "done"


# ---------------------------------------------------------------------------
# UC2 — news_id click
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_intent_news_click(demo_clock, monkeypatch, tmp_path):
    """UC2: news_id only → spawn_theme + 4 spawn_window (chart+text+counter+news) + done."""
    import backend.llm as L
    import backend.orchestrator as O

    monkeypatch.setattr(L, "FIXTURES_DIR", tmp_path / "fixtures")
    # Force the narration into the deterministic-fallback branch (no API key,
    # no fixtures) so this test stays offline-safe.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    L.reset_budget()

    from backend.ws_manager import ConnectionManager

    mgr = ConnectionManager()
    captured: list[tuple[str, dict]] = []

    async def spy(op, payload):
        captured.append((op, payload))
        return 0

    mgr.emit = spy  # type: ignore[assignment]

    await O.handle_intent(
        "intent_uc2",
        {"news_id": "evt_apr5_crash"},
        manager=mgr,
        clock=demo_clock,
    )

    # Before yielding, the synchronous spawn ops + done must all be emitted.
    ops_sync = [op for op, _ in captured]
    assert ops_sync.count("spawn_theme") == 1
    assert ops_sync.count("spawn_window") == 4
    # UC2 stays a context view — no recommendation override.
    assert "intent_recommendation" not in ops_sync
    assert ops_sync[-1] == "done"

    # Now let the fire-and-forget narration task settle (it'll fall back to the
    # deterministic body and emit one update_window after `done`).
    await asyncio.sleep(0)
    ops = [op for op, _ in captured]
    assert ops.count("update_window") == 1

    # The chart window must reference a curve_key.
    chart_spawn = next(
        p for op, p in captured
        if op == "spawn_window" and p.get("window_type") == "chart"
    )
    assert len(chart_spawn["curve_keys"]) == 1

    # The news window must carry the original news_id and a non-empty headline.
    news_spawn = next(
        p for op, p in captured
        if op == "spawn_window" and p.get("window_type") == "news"
    )
    assert news_spawn["spec"]["news_id"] == "evt_apr5_crash"
    assert news_spawn["spec"]["headline"]

    # And we must spawn one counter + one text window for the breakdown lens.
    types = [p.get("window_type") for op, p in captured if op == "spawn_window"]
    assert set(types) == {"chart", "text", "counter", "news"}


@pytest.mark.asyncio
async def test_handle_intent_news_click_curve_mapping(demo_clock, monkeypatch, tmp_path):
    """UC2 chart curve should follow the news_id pattern."""
    import backend.llm as L
    import backend.orchestrator as O

    monkeypatch.setattr(L, "FIXTURES_DIR", tmp_path / "fixtures")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    L.reset_budget()

    from backend.ws_manager import ConnectionManager

    cases = [
        ("forecast_revision_pro_de_wnd_ec00_f", "pro_de_wnd_ec00_f"),
        ("forecast_revision_pro_de_spv_ec00_f", "pro_de_spv_ec00_f"),
        ("price_negative_pri_de_spot_h", "pri_de_spot_h"),
        (
            "optimeering_range_optimeering_no1_imbalance_quantile",
            "optimeering_no1_imbalance_quantile",
        ),
    ]
    for nid, want_curve in cases:
        mgr = ConnectionManager()
        captured: list[tuple[str, dict]] = []

        async def spy(op, payload, _c=captured):
            _c.append((op, payload))
            return 0

        mgr.emit = spy  # type: ignore[assignment]
        await O.handle_intent(
            f"intent_uc2_{nid}",
            {"news_id": nid},
            manager=mgr,
            clock=demo_clock,
        )
        chart_spawn = next(
            p for op, p in captured
            if op == "spawn_window" and p.get("window_type") == "chart"
        )
        assert chart_spawn["curve_keys"] == [want_curve], (nid, chart_spawn["curve_keys"])
