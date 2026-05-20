import json, os
import pytest
from pathlib import Path


def test_budget_records_haiku_cost():
    from backend.llm import BudgetGuard
    bg = BudgetGuard()
    bg.record("claude-haiku-4-5", {"input_tokens": 1000, "output_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0})
    expected = (1000 * 1.0 + 100 * 5.0) / 1_000_000
    assert abs(bg.total_spent_usd - expected) < 1e-9


def test_budget_cache_read_cheap():
    from backend.llm import BudgetGuard
    bg = BudgetGuard()
    bg.record("claude-haiku-4-5", {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 8000})
    expected = 8000 * 0.10 / 1_000_000
    assert abs(bg.total_spent_usd - expected) < 1e-9


def test_budget_hard_limit_raises():
    from backend.llm import BudgetGuard, BudgetExceeded
    bg = BudgetGuard(policy="hard_fail")
    bg.total_spent_usd = 179.99
    with pytest.raises(BudgetExceeded):
        bg.record("claude-sonnet-4-6", {"input_tokens": 100_000_000, "output_tokens": 0})


def test_budget_warn_only_no_raise(caplog):
    from backend.llm import BudgetGuard
    bg = BudgetGuard(policy="warn_only")
    bg.total_spent_usd = 200.0
    bg.check()  # should warn, not raise


def test_make_fake_response_tool_use():
    from backend.llm import _make_fake_response
    r = _make_fake_response({
        "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": "toolu_x", "name": "apply_layout", "input": {"thesis_key": "de_duck_curve", "theme": "DE"}}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    })
    assert r.stop_reason == "tool_use"
    assert r.content[0].type == "tool_use"
    assert r.content[0].name == "apply_layout"
    assert r.content[0].input == {"thesis_key": "de_duck_curve", "theme": "DE"}


def test_make_fake_response_text():
    from backend.llm import _make_fake_response
    r = _make_fake_response({
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "hello"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    })
    assert r.content[0].type == "text"
    assert r.content[0].text == "hello"


@pytest.mark.asyncio
async def test_replay_loads_fixture(tmp_path, monkeypatch):
    import backend.llm as L
    fix_dir = tmp_path / "llm_fixtures"
    fix_dir.mkdir()
    (fix_dir / "test_fix.json").write_text(json.dumps({
        "fixture_key": "test_fix",
        "response": {
            "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "id": "toolu_1", "name": "apply_layout", "input": {"thesis_key": "de_duck_curve", "theme": "DE"}}],
            "usage": {"input_tokens": 10, "output_tokens": 1},
        },
    }))
    monkeypatch.setattr(L, "FIXTURES_DIR", fix_dir)
    monkeypatch.setenv("LLM_REPLAY", "1")
    L.reset_budget()
    r = await L.chat(model="claude-haiku-4-5", system="x", messages=[{"role": "user", "content": "hi"}], fixture_key="test_fix")
    assert r.stop_reason == "tool_use"
    assert r.content[0].name == "apply_layout"


@pytest.mark.asyncio
async def test_replay_missing_fixture_raises(tmp_path, monkeypatch):
    import backend.llm as L
    monkeypatch.setattr(L, "FIXTURES_DIR", tmp_path / "nope")
    monkeypatch.setenv("LLM_REPLAY", "1")
    L.reset_budget()
    with pytest.raises(FileNotFoundError):
        await L.chat(model="claude-haiku-4-5", system="x", messages=[{"role": "user", "content": "hi"}], fixture_key="nope")


@pytest.mark.asyncio
async def test_unknown_provider_raises(monkeypatch):
    import backend.llm as L
    monkeypatch.setenv("LLM_REPLAY", "0")
    monkeypatch.setenv("LLM_PROVIDER", "xyz")
    L.reset_budget()
    with pytest.raises(RuntimeError):
        await L.chat(model="claude-haiku-4-5", system="x", messages=[{"role": "user", "content": "hi"}], fixture_key="ignored")
