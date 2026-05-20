"""FastAPI app — REST endpoints + WS / + lifespan validators + CORS.

Single uvicorn worker (per r2-backend §8.2). `/intent` returns HTTP 202 and
the orchestrator runs as an asyncio.create_task held in a strong-ref set
(Python 3.12 GC-safety per r2-backend §3).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env.local")

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.cache import get_meta, load_index, read_ts
from backend.clock import VirtualNowClock
from backend.news import DerivedNewsEngine
from backend.orchestrator import handle_intent
from backend.templates import restore_template as t_restore
from backend.templates import save_template as t_save
from backend.validators import _validate_invariants
from backend.ws_manager import ConnectionManager

log = logging.getLogger("volta.main")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Strong-ref set for in-flight /intent tasks (Python 3.12 GC-safe, r2-backend §3)
_inflight_intents: set[asyncio.Task] = set()

manager = ConnectionManager()
clock: VirtualNowClock | None = None
news_engine: DerivedNewsEngine | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: invariants + cache index + clock + news engine. Shutdown: drain tasks."""
    global clock, news_engine
    log.info("Volta backend starting...")

    strict = os.environ.get("VOLTA_LENIENT_STARTUP", "0") != "1"
    if strict:
        try:
            _validate_invariants(strict=True)
            log.info("startup invariants OK")
        except RuntimeError as exc:
            log.error("STARTUP INVARIANT FAILURE:\n%s", exc)
            raise
    else:
        errs = _validate_invariants(strict=False)
        for e in errs:
            log.warning("lenient invariant error: %s", e)

    load_index()
    clock = VirtualNowClock.load_from_json()
    # Advance to 14:00 UTC (= 15:00 CET, mid-afternoon) so the canvas chart
    # has a populated 00:00..14:00 window. Demo arc lives on March 6.
    clock.tick(56)  # 56 × 15min = 14h
    news_engine = DerivedNewsEngine(clock)

    # Seed the WS ringbuffer with the current virtual_now so any client that
    # connects (now or later, replaying since=0) immediately syncs its header.
    await manager.emit(
        "clock_tick",
        {
            "virtual_now": clock.iso(),
            "tick_count": clock.tick_count,
            "fired_news_ids": [],
        },
    )

    log.info(
        "Volta backend ready: clock=%s demo_day=%s",
        clock.iso(),
        clock.demo_day,
    )

    yield

    # Shutdown: cancel any in-flight orchestrator tasks
    for t in list(_inflight_intents):
        t.cancel()
    if _inflight_intents:
        await asyncio.gather(*_inflight_intents, return_exceptions=True)
    log.info("Volta backend stopped.")


app = FastAPI(title="Volta Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------- Pydantic request schemas ----------------


class IntentRequest(BaseModel):
    text: str | None = None
    news_id: str | None = None
    canvas_state: dict = Field(default_factory=dict)
    # explicit mode from frontend: "create" | "edit" | "explain". Falls back to
    # heuristic (Haiku classifier) when missing.
    mode: str | None = None


class TickRequest(BaseModel):
    steps: int = Field(ge=1, le=96)


class TemplateSaveRequest(BaseModel):
    name: str
    canvas_snapshot: dict


class TemplateRestoreRequest(BaseModel):
    name: str


class SearchEnrichRequest(BaseModel):
    window_id: str | None = None
    intent_id: str | None = None
    theme_id: str | None = None
    context: dict = Field(default_factory=dict)


# ---------------- REST endpoints ----------------


@app.post("/intent", status_code=202)
async def post_intent(req: IntentRequest):
    intent_id = str(uuid.uuid4())
    task = asyncio.create_task(
        handle_intent(
            intent_id,
            req.model_dump(),
            manager=manager,
            clock=clock,
            news_engine=news_engine,
        ),
        name=f"intent:{intent_id}",
    )
    _inflight_intents.add(task)
    task.add_done_callback(_inflight_intents.discard)
    return {"intent_id": intent_id, "status": "processing", "ws_channel": "/ws"}


@app.post("/tick")
async def post_tick(req: TickRequest):
    assert clock is not None and news_engine is not None
    new_now = clock.tick(req.steps)
    events = news_engine.events_at(new_now)

    fired_news_ids: list[str] = []
    for ev in events:
        fired_news_ids.append(ev.news_id)
        await manager.emit("news_event", {"event": asdict(ev)})

    await manager.emit(
        "clock_tick",
        {
            "virtual_now": new_now.isoformat(),
            "tick_count": clock.tick_count,
            "fired_news_ids": fired_news_ids,
        },
    )
    return {"virtual_now": new_now.isoformat(), "fired_news_ids": fired_news_ids}


@app.post("/template/save")
async def post_template_save(req: TemplateSaveRequest):
    try:
        return t_save(req.name, req.canvas_snapshot)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_name", "message": str(exc)},
        )


@app.post("/template/restore")
async def post_template_restore(req: TemplateRestoreRequest):
    try:
        return t_restore(req.name)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": "template_not_found", "message": req.name},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_name", "message": str(exc)},
        )


@app.get("/curves/index")
async def get_curves_index():
    idx = load_index()
    entries = idx.get("entries", {})
    curves = [
        {
            "curve_key": k,
            "type": m.get("type"),
            "area": m.get("area"),
            "unit": m.get("unit"),
            "frequency": m.get("frequency"),
            "source_curve": m.get("source_curve"),
        }
        for k, m in entries.items()
    ]
    return {
        "demo_day": idx.get("demo_day"),
        "cache_window": idx.get("window"),
        "curves": curves,
    }


@app.get("/curve/raw")
async def get_curve_raw(
    curve_key: str,
    t_from: str | None = None,
    t_to: str | None = None,
):
    import pandas as pd

    try:
        meta = get_meta(curve_key)
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail={"error": "unknown_curve", "message": curve_key},
        )
    try:
        from backend.cache import read_latest_instance, read_optimeering
        mtype = meta.get("type") if isinstance(meta, dict) else None
        if mtype == "instance":
            df = read_latest_instance(curve_key, clock)
        elif mtype == "optimeering":
            df_o = read_optimeering(curve_key, clock)
            # Flatten optimeering wide DF to a {ts, value} timeseries for the chart.
            if df_o is None or df_o.empty:
                df = pd.DataFrame(columns=["ts", "value"])
            else:
                value_col = next((c for c in ("value_point", "value_50", "value_q50", "value") if c in df_o.columns), None)
                if value_col is None:
                    df = pd.DataFrame(columns=["ts", "value"])
                else:
                    ts_col = "prediction_for" if "prediction_for" in df_o.columns else "event_time"
                    df = df_o[[ts_col, value_col]].rename(columns={ts_col: "ts", value_col: "value"}).copy()
        else:
            df = read_ts(curve_key, clock)
    except Exception as exc:  # noqa: BLE001 — surface cache errors as 500
        raise HTTPException(
            status_code=500,
            detail={"error": "cache_read_failed", "message": str(exc)},
        )
    if t_from:
        df = df[df["ts"] >= pd.Timestamp(t_from)]
    if t_to:
        df = df[df["ts"] <= pd.Timestamp(t_to)]
    return {
        "curve_key": curve_key,
        "unit": meta.get("unit"),
        "area": meta.get("area"),
        "virtual_now": clock.iso() if clock is not None else None,
        "rows": [
            {"ts": row["ts"].isoformat(), "value": float(row["value"])}
            for _, row in df.iterrows()
        ],
        "row_count": int(len(df)),
    }


@app.post("/search/enrich", status_code=202)
async def post_search_enrich(req: SearchEnrichRequest):
    from backend import search as search_mod

    search_id = str(uuid.uuid4())
    task = asyncio.create_task(
        search_mod.enrich(search_id, req.model_dump(), manager=manager, clock=clock),
        name=f"search:{search_id}",
    )
    _inflight_intents.add(task)
    task.add_done_callback(_inflight_intents.discard)
    return {"search_id": search_id, "status": "processing"}


@app.post("/warmup")
async def post_warmup():
    if os.environ.get("LLM_REPLAY", "0") == "1":
        return {"cache_warm": False, "mode": "replay", "skipped": True}
    return {"cache_warm": True, "mode": "live"}


@app.post("/admin/reset_news_cooldowns")
async def post_reset_news():
    assert news_engine is not None
    news_engine.reset_cooldowns()
    return {"reset": True}


@app.post("/admin/kill_switch")
async def post_kill_switch():
    """Hard reset: cancel in-flight intents, drop the WS ringbuffer, clear
    in-process caches, reset news cooldowns + LLM budget, advance the clock
    back to mid-afternoon. Frontends get a single `clear_canvas` + fresh
    `clock_tick` so their store resets atomically.
    """
    from backend.cache import clear_cache
    from backend.clock import VirtualNowClock
    from backend.llm import reset_budget

    global clock, news_engine

    # 1. Cancel anything still streaming
    cancelled = 0
    for t in list(_inflight_intents):
        if not t.done():
            t.cancel()
            cancelled += 1
    if _inflight_intents:
        await asyncio.gather(*list(_inflight_intents), return_exceptions=True)
    _inflight_intents.clear()

    # 2. Clear ringbuffer + in-flight send queues
    await manager.clear_buffer()

    # 3. Reset module-level caches + cooldowns + budget
    clear_cache()
    reset_budget()
    if news_engine is not None:
        news_engine.reset_cooldowns()
    clock = VirtualNowClock.load_from_json()
    clock.tick(56)
    news_engine = DerivedNewsEngine(clock)

    # 4. Push a fresh clock_tick + an empty clear_canvas to every client.
    await manager.emit(
        "clock_tick",
        {
            "virtual_now": clock.iso(),
            "tick_count": clock.tick_count,
            "fired_news_ids": [],
        },
    )
    await manager.emit("clear_canvas", {"reason": "kill_switch"})

    log.info("kill switch: cancelled %d task(s), buffer cleared, clock=%s", cancelled, clock.iso())
    return {"ok": True, "cancelled_tasks": cancelled, "virtual_now": clock.iso()}


# ---------------- WebSocket ----------------


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    client_id = ws.query_params.get("client_id") or str(uuid.uuid4())
    try:
        since = int(ws.query_params.get("since", "0"))
    except ValueError:
        since = 0
    await manager.connect(ws, client_id=client_id, since=since)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(client_id)
    except Exception as exc:  # noqa: BLE001
        log.debug("ws %s exited with %s", client_id, exc)
        await manager.disconnect(client_id)
