"""FastAPI lenient-startup tests — boot the app without requiring a populated cache."""
from __future__ import annotations

import pytest


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Boot the app in lenient mode + REPLAY=1 so we never hit a real LLM."""
    monkeypatch.setenv("VOLTA_LENIENT_STARTUP", "1")
    monkeypatch.setenv("LLM_REPLAY", "1")
    # Point LLM fixtures at an empty dir so orchestrator must fall back gracefully.
    import backend.llm as L

    monkeypatch.setattr(L, "FIXTURES_DIR", tmp_path / "fixtures")
    L.reset_budget()

    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as c:
        yield c


def test_app_starts_in_lenient_mode(client):
    r = client.get("/docs")
    assert r.status_code == 200


def test_post_intent_returns_202(client):
    r = client.post(
        "/intent",
        json={"text": "I want to trade Germany's solar duck curve"},
    )
    assert r.status_code == 202
    body = r.json()
    assert "intent_id" in body
    assert body["ws_channel"] == "/ws"
    assert body["status"] == "processing"


def test_post_intent_with_news_id(client):
    r = client.post("/intent", json={"news_id": "evt_apr5_crash"})
    assert r.status_code == 202


def test_post_tick_advances_clock(client):
    r = client.post("/tick", json={"steps": 4})
    assert r.status_code == 200
    body = r.json()
    assert "virtual_now" in body
    assert "fired_news_ids" in body
    assert isinstance(body["fired_news_ids"], list)


def test_post_tick_validates_steps(client):
    # steps must be 1-96
    r = client.post("/tick", json={"steps": 0})
    assert r.status_code == 422

    r = client.post("/tick", json={"steps": 200})
    assert r.status_code == 422


def test_template_save_invalid_name(client):
    r = client.post(
        "/template/save",
        json={"name": "bad/name", "canvas_snapshot": {}},
    )
    assert r.status_code == 422


def test_template_restore_missing(client):
    r = client.post("/template/restore", json={"name": "nonexistent_xyz"})
    assert r.status_code == 404


def test_template_save_restore_roundtrip(client):
    snap = {
        "windows": [{"id": "w1"}],
        "themes": ["t1"],
        "virtual_now": "2026-04-05T14:00:00Z",
    }
    r = client.post(
        "/template/save",
        json={"name": "demo_a", "canvas_snapshot": snap},
    )
    assert r.status_code == 200

    r2 = client.post("/template/restore", json={"name": "demo_a"})
    assert r2.status_code == 200
    assert r2.json()["canvas_snapshot"] == snap


def test_warmup_replay_skips(client):
    r = client.post("/warmup")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "replay"


def test_reset_news_cooldowns(client):
    r = client.post("/admin/reset_news_cooldowns")
    assert r.status_code == 200
    assert r.json() == {"reset": True}


def test_curve_raw_unknown_400(client):
    r = client.get("/curve/raw?curve_key=nonexistent_xyz")
    assert r.status_code == 400


def test_cors_headers_for_localhost(client):
    """Preflight OPTIONS from localhost:3000 must be allowed by CORSMiddleware."""
    r = client.options(
        "/intent",
        headers={
            "origin": "http://localhost:3000",
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )
    # FastAPI/Starlette returns 200 for valid preflight
    assert r.status_code in (200, 204)
    assert (
        r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    )
