"""Edge-case battery. Covers degradation paths, races, and robustness."""
import asyncio
import json
import os
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"


# ---------------------------------------------------------------------------
# 1. Missing fixture → orchestrator degrades gracefully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_fixture_does_not_crash_demo(tmp_path, monkeypatch):
    """Orchestrator with no fixture file: regex fallback still emits valid sequence."""
    import backend.llm as L
    monkeypatch.setattr(L, "FIXTURES_DIR", tmp_path / "empty_fixtures")
    L.reset_budget()

    from backend.ws_manager import ConnectionManager
    from backend.clock import VirtualNowClock
    import backend.orchestrator as O

    mgr = ConnectionManager()
    captured = []

    async def spy(op, payload):
        captured.append(op)
        return 0

    mgr.emit = spy

    await O.handle_intent(
        "e1",
        {"text": "Germany solar duck curve"},
        manager=mgr,
        clock=VirtualNowClock(),
    )
    assert "spawn_theme" in captured
    assert "done" in captured  # always emitted in finally


# ---------------------------------------------------------------------------
# 2. BudgetGuard
# ---------------------------------------------------------------------------

def test_budget_hard_fail_above_180():
    from backend.llm import BudgetGuard, BudgetExceeded
    g = BudgetGuard(policy="hard_fail")
    g.total_spent_usd = 179.9
    with pytest.raises(BudgetExceeded):
        # 100M sonnet output tokens = 100 × 15 = $1500 → puts us way over
        g.record("claude-sonnet-4-6", {"input_tokens": 0, "output_tokens": 100_000_000})


def test_budget_warn_only_does_not_raise():
    from backend.llm import BudgetGuard
    g = BudgetGuard(policy="warn_only")
    g.total_spent_usd = 200.0
    # Should not raise
    g.check()
    assert g.total_spent_usd == 200.0


# ---------------------------------------------------------------------------
# 3. Forbidden chart color → lifespan validator fails
# ---------------------------------------------------------------------------

def test_forbidden_color_makes_strict_invariants_fail(monkeypatch):
    import sys
    import types
    from backend import validators
    fake = types.ModuleType("backend.layouts")
    fake.LAYOUTS = {
        "de_duck_curve": {
            "windows": [
                {"window_type": "chart", "spec": {"annotations": [{"color": "#ff5f00"}]}},
                {"window_type": "counter", "spec": {"points": [{"claim": "x"}]}},
            ]
        },
        "de_price_crash": {
            "windows": [{"window_type": "counter", "spec": {"points": [{"claim": "x"}]}}]
        },
        "dk1_se4_spread": {
            "windows": [{"window_type": "counter", "spec": {"points": [{"claim": "x"}]}}]
        },
    }
    fake.all_curve_keys = lambda: set()
    monkeypatch.setitem(sys.modules, "backend.layouts", fake)
    import backend
    monkeypatch.setattr(backend, "layouts", fake, raising=False)

    errs = validators._check_no_forbidden_chart_colors()
    assert any("#ff5f00" in e for e in errs)


# ---------------------------------------------------------------------------
# 4. Empty counter-claims → validator fails
# ---------------------------------------------------------------------------

def test_empty_counter_claims_makes_invariants_fail(monkeypatch):
    import sys
    import types
    from backend import validators
    fake = types.ModuleType("backend.layouts")
    fake.LAYOUTS = {
        "de_duck_curve": {
            "windows": [{"window_type": "counter", "spec": {"points": []}}]
        },
        "de_price_crash": {
            "windows": [{"window_type": "chart"}]  # no counter at all
        },
        "dk1_se4_spread": {
            "windows": [{"window_type": "counter", "spec": {"points": [{"claim": "y"}]}}]
        },
    }
    fake.all_curve_keys = lambda: set()
    monkeypatch.setitem(sys.modules, "backend.layouts", fake)
    import backend
    monkeypatch.setattr(backend, "layouts", fake, raising=False)

    errs = validators._check_counter_evidence_nonempty()
    assert any("de_duck_curve" in e for e in errs)
    assert any("de_price_crash" in e for e in errs)


# ---------------------------------------------------------------------------
# 5. Residual mismatch → validator catches it
# ---------------------------------------------------------------------------

def test_residual_false_flag_caught_by_validator(monkeypatch, tmp_path):
    from backend import validators
    p = tmp_path / "pcb.json"
    p.write_text(json.dumps({
        "thesis_keys": {
            "de_duck_curve": {"residual_check_ok": True},
            "de_price_crash": {"residual_check_ok": False},  # bad
            "dk1_se4_spread": {"residual_check_ok": True},
        }
    }))
    monkeypatch.setattr(validators, "PRECOMPUTED_BREAKDOWNS_PATH", p)
    errs = validators._check_precomputed_breakdowns_residual_ok(lenient=False)
    assert any("de_price_crash" in e for e in errs)


# ---------------------------------------------------------------------------
# 6. WS replay-gap on overflow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ws_replay_gap_when_since_too_old():
    from backend.ws_manager import ConnectionManager, RINGBUFFER_MAXLEN
    m = ConnectionManager()
    # Emit MORE than ringbuffer capacity
    for i in range(RINGBUFFER_MAXLEN + 100):
        await m.emit("noop", {"i": i})

    class FakeWS:
        def __init__(self):
            self.sent = []

        async def accept(self):
            pass

        async def send_json(self, d):
            self.sent.append(d)
            await asyncio.sleep(0)

        async def receive_text(self):
            await asyncio.sleep(60.0)

    ws = FakeWS()
    await m.connect(ws, client_id="gap_test", since=10)  # 10 << oldest in buffer (~100)
    for _ in range(20):
        await asyncio.sleep(0.01)
        if any(f.get("op") == "error" for f in ws.sent):
            break
    errors = [f for f in ws.sent if f.get("op") == "error"]
    assert len(errors) >= 1
    assert errors[0]["payload"]["code"] == "REPLAY_GAP"
    assert errors[0]["payload"]["fatal"] is False
    await m.disconnect("gap_test")


# ---------------------------------------------------------------------------
# 7. 10 parallel /intent → all complete, no GC
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def server():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = os.environ.copy()
    env["LLM_REPLAY"] = "1"
    proc = subprocess.Popen(
        [str(ROOT / ".venv/bin/uvicorn"), "backend.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 20.0
    ready = False
    while time.time() < deadline:
        try:
            if httpx.get(f"{base}/docs", timeout=1.0).status_code == 200:
                ready = True
                break
        except Exception:
            time.sleep(0.3)
    if not ready:
        proc.terminate()
        proc.wait(timeout=5)
        raise RuntimeError("uvicorn boot failed")
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.asyncio
async def test_10_parallel_intents_all_complete(server):
    base = server
    async with httpx.AsyncClient(timeout=10.0) as h:
        async def post():
            r = await h.post(f"{base}/intent", json={"text": "Solar duck curve"})
            return r.status_code

        results = await asyncio.gather(*[post() for _ in range(10)])
    assert all(r == 202 for r in results)


# ---------------------------------------------------------------------------
# 8. Concurrent template save (no torn file)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_template_save_no_torn_file(server, tmp_path):
    base = server
    snap = {"windows": [{"id": "w1"}], "themes": ["t1"], "virtual_now": "2026-04-05T01:00:00Z"}
    async with httpx.AsyncClient() as h:
        async def save(i):
            return await h.post(
                f"{base}/template/save",
                json={"name": "race_a", "canvas_snapshot": {**snap, "i": i}},
            )

        rs = await asyncio.gather(*[save(i) for i in range(5)])
    for r in rs:
        assert r.status_code == 200
    # Restore and verify it's valid JSON
    r = httpx.post(f"{base}/template/restore", json={"name": "race_a"})
    assert r.status_code == 200
    data = r.json()
    assert "canvas_snapshot" in data
    assert "schema_version" in data


# ---------------------------------------------------------------------------
# 9. News cooldown (same news within 30min suppressed)
# ---------------------------------------------------------------------------

def test_news_cooldown_suppresses_repeat():
    from datetime import timedelta
    from backend.clock import VirtualNowClock
    from backend.news import DerivedNewsEngine

    clock = VirtualNowClock()
    clock.tick(56)  # 14:00 UTC
    eng = DerivedNewsEngine(clock=clock)
    t = clock.now()
    e1 = eng.events_at(t)
    # Same news_ids within 30min → suppressed
    e2 = eng.events_at(t + timedelta(minutes=15))
    if e1:
        # No event with the same news_id as any in e1
        e1_ids = {ev.news_id for ev in e1}
        e2_ids = {ev.news_id for ev in e2}
        assert not (e1_ids & e2_ids), "cooldown should suppress same news_id"


# ---------------------------------------------------------------------------
# 10. DST transition transparent
# ---------------------------------------------------------------------------

def test_dst_cache_reads_consistent():
    from backend.cache import clear_cache, load_index, read_ts
    from backend.clock import VirtualNowClock
    clear_cache()
    load_index()
    c = VirtualNowClock()
    c.reset(datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc))
    df1 = read_ts("pri_de_spot_h", c)
    c.reset(datetime(2026, 3, 29, 3, 0, tzinfo=timezone.utc))
    df2 = read_ts("pri_de_spot_h", c)
    assert len(df2) >= len(df1), f"DST transition lost rows: {len(df1)} -> {len(df2)}"


# ---------------------------------------------------------------------------
# 11. Naive datetime → ValueError
# ---------------------------------------------------------------------------

def test_naive_datetime_raises_value_error():
    from backend.clock import VirtualNowClock
    from backend.news import DerivedNewsEngine
    eng = DerivedNewsEngine(clock=VirtualNowClock())
    with pytest.raises(ValueError):
        eng.events_at(datetime(2026, 4, 5, 14, 0))  # naive


# ---------------------------------------------------------------------------
# 12. Atomic template write (broken JSON does not corrupt the previous file)
# ---------------------------------------------------------------------------

def test_template_atomic_write_preserves_previous(tmp_path, monkeypatch):
    import backend.templates as T
    monkeypatch.setattr(T, "TEMPLATES_DIR", tmp_path)
    snap1 = {"windows": [{"id": "old"}], "themes": ["t"], "virtual_now": "2026-04-05T00:00:00Z"}
    T.save_template("atom", snap1)
    # Now overwrite with a snapshot containing non-serializable garbage →
    # should raise BEFORE os.replace
    class Bad:
        pass
    snap2 = {"windows": [Bad()], "themes": ["t2"], "virtual_now": "x"}
    with pytest.raises(Exception):
        T.save_template("atom", snap2)
    # Old file must still be intact + readable
    payload = T.restore_template("atom")
    assert payload["canvas_snapshot"]["themes"] == ["t"]


# ---------------------------------------------------------------------------
# 13. Strict lifespan raises when fixtures missing
# ---------------------------------------------------------------------------

def test_strict_lifespan_raises_when_fixtures_missing(tmp_path, monkeypatch):
    from backend import validators
    monkeypatch.setattr(validators, "LLM_FIXTURES_DIR", tmp_path / "no_fixtures")
    errs = validators._check_fixtures_present()
    assert len(errs) >= 1
    assert any("missing" in e.lower() for e in errs)


# ---------------------------------------------------------------------------
# 14. Reset budget singleton
# ---------------------------------------------------------------------------

def test_reset_budget_clears_state():
    import backend.llm as L
    L.reset_budget()
    g = L.get_budget()
    g.total_spent_usd = 50.0
    L.reset_budget()
    assert L.get_budget().total_spent_usd == 0.0


# ---------------------------------------------------------------------------
# 15. Tick negative → ValueError
# ---------------------------------------------------------------------------

def test_clock_negative_tick_raises():
    from backend.clock import VirtualNowClock
    c = VirtualNowClock()
    with pytest.raises(ValueError):
        c.tick(-1)


# ---------------------------------------------------------------------------
# 16. Resolve unknown thesis_key → KeyError
# ---------------------------------------------------------------------------

def test_resolve_unknown_thesis_key_raises():
    from backend.layouts import resolve
    from backend.clock import VirtualNowClock
    with pytest.raises(KeyError):
        resolve("nonexistent_thesis", VirtualNowClock())
