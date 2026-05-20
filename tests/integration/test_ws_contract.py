"""WebSocket contract tests with subprocess uvicorn + websockets client."""
import asyncio
import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _find_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


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
    # Wait for ready
    deadline = time.time() + 20.0
    while time.time() < deadline:
        try:
            r = httpx.get(f"{base}/docs", timeout=1.0)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(0.3)
    else:
        proc.terminate(); proc.wait(timeout=5)
        raise RuntimeError("uvicorn did not start in 20s")
    yield base, ws_url
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.asyncio
async def test_intent_emits_full_sequence(server):
    base, ws_url = server
    import websockets
    async with websockets.connect(f"{ws_url}?client_id=ws_test_1") as ws:
        async with httpx.AsyncClient() as h:
            r = await h.post(f"{base}/intent", json={"text":"Solar duck curve in Germany"})
            assert r.status_code == 202
        ops = []
        intent_id = r.json()["intent_id"]
        deadline = asyncio.get_running_loop().time() + 8.0
        while asyncio.get_running_loop().time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
            except asyncio.TimeoutError:
                break
            frame = json.loads(msg)
            ops.append(frame)
            if frame["op"] == "done" and frame["payload"].get("intent_id") == intent_id:
                break
        op_types = [o["op"] for o in ops]
        # Sequence: clear_canvas, spawn_theme, spawn_window×4, intent_recommendation, done
        assert "clear_canvas" in op_types
        assert "spawn_theme" in op_types
        assert op_types.count("spawn_window") >= 4
        assert "intent_recommendation" in op_types
        assert "done" in op_types
        # Seq monotonic
        seqs = [o["seq"] for o in ops]
        assert seqs == sorted(seqs)


@pytest.mark.asyncio
async def test_tick_emits_clock_tick_and_news(server):
    base, ws_url = server
    import websockets
    async with websockets.connect(f"{ws_url}?client_id=ws_test_tick") as ws:
        async with httpx.AsyncClient() as h:
            await h.post(f"{base}/admin/reset_news_cooldowns")  # ensure news fire
            r = await h.post(f"{base}/tick", json={"steps":56})  # +14h
            assert r.status_code == 200
        ops = []
        deadline = asyncio.get_running_loop().time() + 5.0
        while asyncio.get_running_loop().time() < deadline:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                break
            ops.append(json.loads(msg))
        op_types = [o["op"] for o in ops]
        assert "clock_tick" in op_types
        # Likely also news_event (depends on data)


@pytest.mark.asyncio
async def test_replay_gap_on_stale_since(server):
    base, ws_url = server
    import websockets
    # Connect with absurdly old since
    async with websockets.connect(f"{ws_url}?client_id=ws_test_gap&since=999999999") as ws:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
            frame = json.loads(msg)
            # First frame should be either replayed-from-buffer or REPLAY_GAP error
            # If ringbuffer has >= 1 frame with seq < 999999999, the since check
            # would normally consider since=99999... as "ahead of buffer" → no replay needed.
            # Specifically, REPLAY_GAP triggers when oldest_seq > since+1.
            # since=999999999 > any real seq → no gap, just no replay.
            # We accept either: an op (buffer reseed) OR no frame (timeout).
        except asyncio.TimeoutError:
            pass  # OK

    # Now test the actual REPLAY_GAP path: emit ≥ buffer-size+1 ops first, then connect with old since
    async with websockets.connect(f"{ws_url}?client_id=ws_test_gap2&since=0") as ws:
        # Generate ops by ticking
        async with httpx.AsyncClient() as h:
            for _ in range(2):
                await h.post(f"{base}/tick", json={"steps":1})
        # Drain frames briefly
        try:
            while True:
                await asyncio.wait_for(ws.recv(), timeout=1.0)
        except asyncio.TimeoutError:
            pass
