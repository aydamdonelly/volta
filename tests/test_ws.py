import asyncio
import pytest


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []
        self._open = True
    async def accept(self):
        pass
    async def send_json(self, data):
        if not self._open:
            raise RuntimeError("ws closed")
        self.sent.append(data)
        # Allow event loop to run drain
        await asyncio.sleep(0)
    async def receive_text(self):
        await asyncio.sleep(1.0)
        return "ping"


@pytest.mark.asyncio
async def test_emit_assigns_monotonic_seq():
    from backend.ws_manager import ConnectionManager
    m = ConnectionManager()
    s1 = await m.emit("spawn_theme", {"x":1})
    s2 = await m.emit("spawn_window", {"x":2})
    s3 = await m.emit("done", {})
    assert s1 == 1 and s2 == 2 and s3 == 3
    assert m.buffer_size() == 3


@pytest.mark.asyncio
async def test_ringbuffer_maxlen():
    from backend.ws_manager import ConnectionManager, RINGBUFFER_MAXLEN
    m = ConnectionManager()
    for i in range(RINGBUFFER_MAXLEN + 50):
        await m.emit("noop", {"i":i})
    assert m.buffer_size() == RINGBUFFER_MAXLEN


@pytest.mark.asyncio
async def test_connect_and_emit_streams_to_client():
    from backend.ws_manager import ConnectionManager
    m = ConnectionManager()
    ws = FakeWS()
    await m.connect(ws, client_id="c1", since=0)
    await m.emit("spawn_theme", {"x":1})
    # let drain run
    for _ in range(20):
        await asyncio.sleep(0.01)
        if ws.sent: break
    assert len(ws.sent) >= 1
    assert ws.sent[0]["op"] == "spawn_theme"
    await m.disconnect("c1")


@pytest.mark.asyncio
async def test_replay_from_since():
    from backend.ws_manager import ConnectionManager
    m = ConnectionManager()
    for i in range(5):
        await m.emit("noop", {"i":i})
    ws = FakeWS()
    await m.connect(ws, client_id="c1", since=2)
    # Should replay frames seq > 2 (i.e., seq 3, 4, 5)
    for _ in range(30):
        await asyncio.sleep(0.01)
        if len(ws.sent) >= 3: break
    seqs = [f["seq"] for f in ws.sent]
    assert 3 in seqs and 4 in seqs and 5 in seqs
    assert 1 not in seqs and 2 not in seqs
    await m.disconnect("c1")


@pytest.mark.asyncio
async def test_replay_gap_when_since_too_old():
    from backend.ws_manager import ConnectionManager, RINGBUFFER_MAXLEN
    m = ConnectionManager()
    for i in range(RINGBUFFER_MAXLEN + 50):
        await m.emit("noop", {"i":i})
    ws = FakeWS()
    await m.connect(ws, client_id="c1", since=10)  # 10 << oldest_seq (50)
    for _ in range(20):
        await asyncio.sleep(0.01)
        if any(f.get("op")=="error" for f in ws.sent): break
    errors = [f for f in ws.sent if f.get("op") == "error"]
    assert len(errors) >= 1
    assert errors[0]["payload"]["code"] == "REPLAY_GAP"
    assert errors[0]["payload"]["fatal"] is False
    await m.disconnect("c1")


@pytest.mark.asyncio
async def test_disconnect_cleans_up():
    from backend.ws_manager import ConnectionManager
    m = ConnectionManager()
    ws = FakeWS()
    await m.connect(ws, client_id="c1", since=0)
    assert m.client_count() == 1
    await m.disconnect("c1")
    assert m.client_count() == 0
