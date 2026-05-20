"""WebSocket ConnectionManager — per-client asyncio.Queue + 500-frame ringbuffer + REPLAY_GAP."""
from __future__ import annotations
import asyncio, json, logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger("volta.ws")

RINGBUFFER_MAXLEN = 500
QUEUE_MAXSIZE = 100


@dataclass
class ClientCtx:
    ws: WebSocket
    send_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=QUEUE_MAXSIZE))
    writer_task: Optional[asyncio.Task] = None


class ConnectionManager:
    """Single-process, in-memory WS-Manager mit Ringpuffer-Replay.

    Per r2-backend §2.2 + Stream-#05 §3.5:
      - 500-Frame-Ringpuffer für ?since=<seq>-Reconnect
      - per-Client asyncio.Queue (maxsize=100), kein Ack-Protokoll
      - ein monotoner seq-Counter prozessweit (nicht pro-client)
      - drop-oldest backpressure, REPLAY_GAP error op on overflow
    """

    def __init__(self) -> None:
        self._clients: dict[str, ClientCtx] = {}
        self._op_buffer: deque[dict[str, Any]] = deque(maxlen=RINGBUFFER_MAXLEN)
        self._seq: int = 0
        self._lock = asyncio.Lock()

    # -------------------- public API --------------------

    async def connect(self, ws: WebSocket, client_id: str, since: int = 0) -> None:
        await ws.accept()
        ctx = ClientCtx(ws=ws)
        self._clients[client_id] = ctx
        ctx.writer_task = asyncio.create_task(self._drain(client_id, ctx))
        await self._replay_from(client_id, since)

    async def disconnect(self, client_id: str) -> None:
        ctx = self._clients.pop(client_id, None)
        if ctx is None:
            return
        if ctx.writer_task is not None and not ctx.writer_task.done():
            ctx.writer_task.cancel()
            try:
                await ctx.writer_task
            except (asyncio.CancelledError, Exception):
                pass

    async def emit(self, op: str, payload: dict[str, Any]) -> int:
        """Eine Op an alle verbundenen Clients senden + im Ringpuffer ablegen.
        Gibt die vergebene seq zurück (für Logging/Tests).
        """
        async with self._lock:
            self._seq += 1
            frame = {
                "op": op,
                "seq": self._seq,
                "ts": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
            }
            self._op_buffer.append(frame)
            seq = self._seq

        for client_id, ctx in list(self._clients.items()):
            try:
                ctx.send_queue.put_nowait(frame)
            except asyncio.QueueFull:
                # Drop-oldest backpressure
                try:
                    ctx.send_queue.get_nowait()
                    ctx.send_queue.task_done()
                except asyncio.QueueEmpty:
                    pass
                try:
                    ctx.send_queue.put_nowait(frame)
                except asyncio.QueueFull:
                    # Still full → client too slow, schedule disconnect
                    asyncio.create_task(self.disconnect(client_id))
        return seq

    def frames_seen(self) -> int:
        return self._seq

    def buffer_size(self) -> int:
        return len(self._op_buffer)

    def client_count(self) -> int:
        return len(self._clients)

    async def clear_buffer(self) -> None:
        """Drop every buffered op + reset seq. Reconnecting clients see a
        fresh canvas. Held lock briefly to avoid mid-emit corruption.
        """
        async with self._lock:
            self._op_buffer.clear()
            self._seq = 0
        # Drain any in-flight per-client send queues so leftover frames don't
        # surface AFTER the kill-switch fires.
        for ctx in list(self._clients.values()):
            while True:
                try:
                    ctx.send_queue.get_nowait()
                    ctx.send_queue.task_done()
                except asyncio.QueueEmpty:
                    break

    # -------------------- private helpers --------------------

    async def _replay_from(self, client_id: str, since: int) -> None:
        ctx = self._clients.get(client_id)
        if ctx is None:
            return
        if not self._op_buffer:
            return
        # Detect REPLAY_GAP: oldest buffered frame > since + 1 means the gap
        # between client's last seen seq and our buffer's oldest is non-empty.
        oldest_seq = self._op_buffer[0]["seq"]
        if oldest_seq > since + 1:
            gap_frame = {
                "op": "error",
                "seq": self._seq,
                "ts": datetime.now(timezone.utc).isoformat(),
                "payload": {
                    "code": "REPLAY_GAP",
                    "message": f"Frames since seq {since} are no longer in buffer (oldest={oldest_seq})",
                    "intent_id": None,
                    "fatal": False,
                },
            }
            try:
                await ctx.send_queue.put(gap_frame)
            except Exception:
                pass
            return
        for frame in list(self._op_buffer):
            if frame["seq"] > since:
                try:
                    await ctx.send_queue.put(frame)
                except Exception:
                    break

    async def _drain(self, client_id: str, ctx: ClientCtx) -> None:
        """Per-Client Writer-Task. Drained send_queue → ws.send_json.
        Stoppt bei WebSocketDisconnect oder CancelledError sauber.
        """
        try:
            while True:
                frame = await ctx.send_queue.get()
                try:
                    await ctx.ws.send_json(frame)
                except (WebSocketDisconnect, RuntimeError) as e:
                    log.debug("ws send failed for %s: %s", client_id, e)
                    ctx.send_queue.task_done()
                    break
                ctx.send_queue.task_done()
        except asyncio.CancelledError:
            raise
        finally:
            self._clients.pop(client_id, None)
