"""REST contract tests using FastAPI TestClient (in-process)."""
import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as c:
        yield c


def test_docs_returns_200(client):
    assert client.get("/docs").status_code == 200


def test_post_intent_202_with_intent_id(client):
    r = client.post("/intent", json={"text":"Why did the price crash on April 5?"})
    assert r.status_code == 202
    body = r.json()
    assert "intent_id" in body
    assert len(body["intent_id"]) >= 8
    assert body["status"] == "processing"
    assert body["ws_channel"] == "/ws"


def test_post_intent_with_news_id(client):
    r = client.post("/intent", json={"news_id":"evt_apr5_crash"})
    assert r.status_code == 202


def test_post_intent_empty_body(client):
    r = client.post("/intent", json={})
    assert r.status_code in (202, 422)


def test_post_intent_validation_422(client):
    r = client.post("/intent", json={"text": 12345})  # text must be string
    assert r.status_code == 422


def test_post_tick_advances(client):
    r = client.post("/tick", json={"steps": 4})
    assert r.status_code == 200
    body = r.json()
    assert "virtual_now" in body
    assert "fired_news_ids" in body
    assert isinstance(body["fired_news_ids"], list)


def test_post_tick_invalid_steps(client):
    r = client.post("/tick", json={"steps": 0})
    assert r.status_code == 422
    r = client.post("/tick", json={"steps": 1000})
    assert r.status_code == 422


def test_template_save_restore_roundtrip(client):
    snap = {"windows":[{"id":"w1","title":"x"}],"themes":["t1"],"virtual_now":"2026-04-05T14:00:00Z"}
    r = client.post("/template/save", json={"name":"contract_a","canvas_snapshot":snap})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    r2 = client.post("/template/restore", json={"name":"contract_a"})
    assert r2.status_code == 200
    assert r2.json()["canvas_snapshot"] == snap


def test_template_save_bad_name(client):
    for bad in ("foo/bar", "..", "FOO", "foo!"):
        r = client.post("/template/save", json={"name":bad,"canvas_snapshot":{}})
        assert r.status_code == 422, f"name {bad!r} not rejected"


def test_template_restore_404(client):
    r = client.post("/template/restore", json={"name":"nonexistent_xyz_123"})
    assert r.status_code == 404


def test_curve_raw_returns_rows(client):
    r = client.get("/curve/raw?curve_key=pri_de_spot_h&t_from=2026-04-05T00:00:00Z&t_to=2026-04-05T23:00:00Z")
    assert r.status_code == 200
    body = r.json()
    assert body["curve_key"] == "pri_de_spot_h"
    assert body["unit"] in ("EUR/MWh","€/MWh")
    assert body["row_count"] >= 0


def test_curve_raw_unknown_curve_400(client):
    r = client.get("/curve/raw?curve_key=nonexistent")
    assert r.status_code == 400


def test_warmup_replay_skips(client):
    r = client.post("/warmup")
    assert r.status_code == 200
    assert r.json()["mode"] == "replay"


def test_admin_reset_news(client):
    r = client.post("/admin/reset_news_cooldowns")
    assert r.status_code == 200
    assert r.json() == {"reset": True}


def test_cors_headers_present(client):
    r = client.options("/intent", headers={"Origin":"http://localhost:3000","Access-Control-Request-Method":"POST"})
    # FastAPI's CORS middleware handles OPTIONS
    assert r.status_code in (200, 204)
    assert "access-control-allow-origin" in {k.lower() for k in r.headers}


def test_cors_127_0_0_1_also_allowed(client):
    r = client.options("/intent", headers={"Origin":"http://127.0.0.1:3000","Access-Control-Request-Method":"POST"})
    assert r.status_code in (200, 204)
