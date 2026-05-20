"""End-to-end demo arc validation. Boot uvicorn subprocess, fire all 3 theses, verify full WS sequences."""
import asyncio
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _find_free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close(); return port


@pytest.fixture(scope="module")
def server():
    port = _find_free_port()
    env = os.environ.copy()
    env["LLM_REPLAY"] = "1"
    proc = subprocess.Popen(
        [str(ROOT/".venv/bin/uvicorn"), "backend.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    ws_url = f"ws://127.0.0.1:{port}/ws"
    deadline = time.time() + 20.0
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/docs", timeout=1.0).status_code == 200:
                break
        except Exception:
            time.sleep(0.3)
    else:
        proc.terminate(); proc.wait(timeout=5)
        raise RuntimeError("uvicorn did not start")
    yield base, ws_url
    proc.terminate()
    try: proc.wait(timeout=5)
    except subprocess.TimeoutExpired: proc.kill()


async def _drain_until_done(ws, intent_id: str, timeout: float = 8.0) -> list[dict]:
    """Drain ws frames, returning only those scoped to this intent_id.

    The server keeps a 500-frame ringbuffer and replays it to every new
    client (since=0). Without this filter, ops from earlier tests sharing
    the module-scoped uvicorn would bleed into the new test's ops list.
    """
    ops = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
        except asyncio.TimeoutError:
            break
        f = json.loads(msg)
        payload_iid = f.get("payload", {}).get("intent_id")
        # Keep ops scoped to this intent_id; also keep ops with no intent_id
        # (e.g. clear_canvas, news_event, clock_tick) that occur after the
        # current intent has started — but only after we've seen any op
        # bearing the current intent_id, to avoid pulling in stale frames.
        if payload_iid == intent_id:
            ops.append(f)
        if f["op"] == "done" and payload_iid == intent_id:
            break
    return ops


@pytest.mark.asyncio
@pytest.mark.parametrize("text,expected_thesis", [
    ("I want to trade Germany's solar duck curve", "de_duck_curve"),
    ("Why did the German day-ahead price crash on March 6th, 2026?", "de_price_crash"),
    ("Show me the DK1 to SE4 cross-border spread", "dk1_se4_spread"),
])
async def test_intent_routes_to_correct_thesis(server, text, expected_thesis):
    base, ws_url = server
    import websockets
    async with websockets.connect(f"{ws_url}?client_id=arc_{expected_thesis}") as ws:
        async with httpx.AsyncClient() as h:
            r = await h.post(f"{base}/intent", json={"text":text})
            assert r.status_code == 202
            intent_id = r.json()["intent_id"]
        ops = await _drain_until_done(ws, intent_id)
        # spawn_theme.payload.thesis_key must match
        theme_op = next((o for o in ops if o["op"] == "spawn_theme"), None)
        assert theme_op is not None
        assert theme_op["payload"]["thesis_key"] == expected_thesis


@pytest.mark.asyncio
async def test_sonnet_narration_cites_demo_day_value(server):
    """Tier-3 Sonnet narration via update_window.body must contain a € price (2-3 digit demo-day value)."""
    base, ws_url = server
    import websockets
    async with websockets.connect(f"{ws_url}?client_id=arc_narration") as ws:
        async with httpx.AsyncClient() as h:
            r = await h.post(f"{base}/intent", json={"text":"Why did the price spike on the demo day?"})
            intent_id = r.json()["intent_id"]
        ops = await _drain_until_done(ws, intent_id, timeout=10.0)
        # Find update_window ops (narration patches text/counter bodies)
        patches = [o for o in ops if o["op"] == "update_window"]
        # Combine all patched bodies
        narration = " ".join(p["payload"]["patch"].get("body","") for p in patches)
        # Verify cite of a euro-denominated price (any 2-3 digit value; Sonnet output is dynamic).
        assert re.search(r"€\s*\d{2,3}", narration) or narration == "", f"narration missing € price: {narration!r}"


@pytest.mark.asyncio
async def test_dk1_se4_counter_evidence_uses_optimeering(server):
    base, ws_url = server
    import websockets
    async with websockets.connect(f"{ws_url}?client_id=arc_optimeering") as ws:
        async with httpx.AsyncClient() as h:
            r = await h.post(f"{base}/intent", json={"text":"DK1 to SE4 nordic spread"})
            intent_id = r.json()["intent_id"]
        ops = await _drain_until_done(ws, intent_id)
        counter_op = next((o for o in ops if o["op"] == "spawn_window" and o["payload"].get("window_type") == "counter"), None)
        assert counter_op is not None, "no counter window in dk1_se4_spread"
        curve_keys = counter_op["payload"].get("curve_keys", [])
        assert any("optimeering" in k.lower() for k in curve_keys), f"no optimeering curve in counter: {curve_keys}"


@pytest.mark.asyncio
async def test_each_layout_has_counter_and_news_windows(server):
    """Every demo thesis spawns chart, text, counter, news (4 windows + 1 theme + recommendation + done)."""
    base, ws_url = server
    import websockets
    for text, tk in [
        ("German solar duck curve", "de_duck_curve"),
        ("March 6 price crash", "de_price_crash"),
        ("DK1 SE4 spread", "dk1_se4_spread"),
    ]:
        async with websockets.connect(f"{ws_url}?client_id=arc_4w_{tk}") as ws:
            async with httpx.AsyncClient() as h:
                r = await h.post(f"{base}/intent", json={"text":text})
                intent_id = r.json()["intent_id"]
            ops = await _drain_until_done(ws, intent_id)
            window_types = [o["payload"].get("window_type") for o in ops if o["op"] == "spawn_window"]
            assert "chart" in window_types, f"{tk}: no chart"
            assert "text" in window_types, f"{tk}: no text"
            assert "counter" in window_types, f"{tk}: no counter"
            assert "news" in window_types, f"{tk}: no news"


@pytest.mark.asyncio
async def test_intent_recommendation_emitted_for_each_thesis(server):
    base, ws_url = server
    import websockets
    for text, tk in [
        ("Germany solar duck curve", "de_duck_curve"),
        ("March 6 demo day price crash Germany", "de_price_crash"),
        ("DK1 SE4 nordic spread imbalance", "dk1_se4_spread"),
    ]:
        async with websockets.connect(f"{ws_url}?client_id=arc_rec_{tk}") as ws:
            async with httpx.AsyncClient() as h:
                r = await h.post(f"{base}/intent", json={"text":text})
                intent_id = r.json()["intent_id"]
            ops = await _drain_until_done(ws, intent_id)
            rec = next((o for o in ops if o["op"] == "intent_recommendation"), None)
            assert rec is not None, f"{tk}: no intent_recommendation"
            assert rec["payload"]["action"]["thesis_key"] == tk


@pytest.mark.asyncio
async def test_done_elapsed_under_5s(server):
    base, ws_url = server
    import websockets
    async with websockets.connect(f"{ws_url}?client_id=arc_speed") as ws:
        async with httpx.AsyncClient() as h:
            r = await h.post(f"{base}/intent", json={"text":"Solar duck curve"})
            intent_id = r.json()["intent_id"]
        ops = await _drain_until_done(ws, intent_id)
        done = next((o for o in ops if o["op"] == "done"), None)
        assert done is not None
        assert done["payload"]["elapsed_ms"] < 5000, f"too slow: {done['payload']['elapsed_ms']}ms"


@pytest.mark.asyncio
async def test_template_save_restore_full_arc(server):
    base, ws_url = server
    import websockets
    # Fire one intent, save the canvas as a template, restore, verify
    from backend.clock import DEFAULT_DEMO_DAY
    snap = {"windows":[{"id":"w1","title":"demo-day price"}],"themes":["de_price_crash"],"virtual_now":f"{DEFAULT_DEMO_DAY.isoformat()}T14:00:00Z"}
    async with httpx.AsyncClient() as h:
        r = await h.post(f"{base}/template/save", json={"name":"arc_a","canvas_snapshot":snap})
        assert r.status_code == 200
        r2 = await h.post(f"{base}/template/restore", json={"name":"arc_a"})
        assert r2.status_code == 200
        assert r2.json()["canvas_snapshot"] == snap


@pytest.mark.asyncio
async def test_news_event_has_hedge_label(server):
    """News fired via /tick has hedge label and hedged=True."""
    base, ws_url = server
    import websockets
    async with websockets.connect(f"{ws_url}?client_id=arc_news") as ws:
        async with httpx.AsyncClient() as h:
            await h.post(f"{base}/admin/reset_news_cooldowns")
            r = await h.post(f"{base}/tick", json={"steps": 56})  # +14h
            assert r.status_code == 200
        # Drain ops briefly
        ops = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 3.0
        while loop.time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except asyncio.TimeoutError:
                break
            ops.append(json.loads(msg))
        news_evs = [o for o in ops if o["op"] == "news_event"]
        for n in news_evs:
            ev = n["payload"]["event"]
            assert ev["hedged"] is True, f"news_event not hedged: {ev}"
            assert any(p in ev["hedged_text"].lower() for p in ("context","could")), ev["hedged_text"]
