"""LLM abstraction: replay-first (default), Anthropic-live, Ollama-stub fallback.

BudgetGuard at $180. Fixture format per phase1/04-budget-replay.md §1.
"""
from __future__ import annotations
import json, logging, os, types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "data" / "llm_fixtures"

# Verified prices (USD per Mtok) — r1-anthropic.md
PRICE = {
    "claude-haiku-4-5":  {"input": 1.00, "output": 5.00,  "cache_write": 1.25, "cache_read": 0.10},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
}
HARD_LIMIT_USD = 180.0
SOFT_LIMIT_USD = 150.0

log = logging.getLogger("volta.llm")


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class BudgetGuard:
    total_spent_usd: float = 0.0
    call_count: int = 0
    policy: str = "hard_fail"  # or "warn_only"

    def record(self, model: str, usage) -> float:
        if model not in PRICE:
            return 0.0
        p = PRICE[model]
        if isinstance(usage, dict):
            def get(obj, key, default=0):
                return obj.get(key, default) or 0
        else:
            def get(obj, key, default=0):
                return getattr(obj, key, default) or 0
        it = get(usage, "input_tokens", 0)
        ot = get(usage, "output_tokens", 0)
        cw = get(usage, "cache_creation_input_tokens", 0)
        cr = get(usage, "cache_read_input_tokens", 0)
        delta = (it * p["input"] + ot * p["output"] + cw * p["cache_write"] + cr * p["cache_read"]) / 1_000_000
        self.total_spent_usd += delta
        self.call_count += 1
        self.check()
        return delta

    def check(self) -> None:
        if self.total_spent_usd > HARD_LIMIT_USD:
            if self.policy == "hard_fail":
                raise BudgetExceeded(f"Budget hard-limit exceeded: ${self.total_spent_usd:.2f} > ${HARD_LIMIT_USD}")
            log.warning("BUDGET SOFT-FAIL: $%.2f > $%d", self.total_spent_usd, HARD_LIMIT_USD)
        elif self.total_spent_usd > SOFT_LIMIT_USD:
            log.warning("BUDGET WARN: $%.2f > $%d", self.total_spent_usd, SOFT_LIMIT_USD)


_budget: BudgetGuard | None = None


def get_budget() -> BudgetGuard:
    global _budget
    if _budget is None:
        _budget = BudgetGuard(policy="warn_only" if os.environ.get("DEMO_MODE", "").lower() == "true" else "hard_fail")
    return _budget


def reset_budget() -> None:
    """Test utility."""
    global _budget
    _budget = None


def _make_fake_response(data: dict) -> types.SimpleNamespace:
    content_blocks = []
    for blk in data.get("content", []):
        if blk["type"] == "tool_use":
            content_blocks.append(types.SimpleNamespace(
                type="tool_use",
                id=blk.get("id", "toolu_replay"),
                name=blk["name"],
                input=blk["input"],
            ))
        elif blk["type"] == "text":
            content_blocks.append(types.SimpleNamespace(type="text", text=blk.get("text", "")))
    usage = types.SimpleNamespace(**data.get("usage", {}))
    return types.SimpleNamespace(
        content=content_blocks,
        stop_reason=data.get("stop_reason", "tool_use"),
        usage=usage,
    )


def _load_fixture(fixture_key: str) -> dict:
    path = FIXTURES_DIR / f"{fixture_key}.json"
    if not path.exists():
        raise FileNotFoundError(f"fixture missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["response"]


async def chat(
    *,
    model: str,
    system,
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    tool_choice: Optional[dict] = None,
    max_tokens: int = 512,
    fixture_key: Optional[str] = None,
    force_live: bool = False,
):
    """Unified chat. Replay if LLM_REPLAY=1 AND not force_live."""
    if not force_live and os.environ.get("LLM_REPLAY", "0") == "1":
        if fixture_key is None:
            raise RuntimeError("LLM_REPLAY=1 but no fixture_key provided")
        data = _load_fixture(fixture_key)
        resp = _make_fake_response(data)
        get_budget().record(model, resp.usage)
        return resp

    # force_live OR LLM_REPLAY=0
    if force_live and not os.environ.get("ANTHROPIC_API_KEY"):
        if fixture_key:
            log.warning("force_live but no API key — fallback to fixture %s", fixture_key)
            data = _load_fixture(fixture_key)
            resp = _make_fake_response(data)
            get_budget().record(model, resp.usage)
            return resp
        raise RuntimeError("force_live and no API key and no fixture")

    provider = os.environ.get("LLM_PROVIDER", "anthropic")
    if provider == "anthropic":
        return await _anthropic_chat(
            model=model, system=system, messages=messages,
            tools=tools, tool_choice=tool_choice, max_tokens=max_tokens,
        )
    if provider == "ollama":
        return await _ollama_chat(
            model=model, system=system, messages=messages,
            tools=tools, max_tokens=max_tokens,
        )
    raise RuntimeError(f"unknown LLM_PROVIDER: {provider!r}")


async def _anthropic_chat(*, model, system, messages, tools, tool_choice, max_tokens):
    from anthropic import AsyncAnthropic  # lazy import
    client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    kwargs: dict = dict(model=model, max_tokens=max_tokens, system=system, messages=messages)
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice
    r = await client.messages.create(**kwargs)
    get_budget().record(model, r.usage)
    return r


async def chat_stream(
    *,
    model: str,
    system,
    messages: list[dict],
    max_tokens: int = 512,
    on_text,  # async callback(full_text_so_far: str) -> None
):
    """Stream a Sonnet text response, calling `on_text(full)` per chunk.

    Always live (no fixture). Falls back to a single `on_text` call with the
    full response if streaming fails. Budget recorded on completion.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("chat_stream: no ANTHROPIC_API_KEY — skipping")
        await on_text("")
        return
    from anthropic import AsyncAnthropic  # lazy
    client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    full = ""
    try:
        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                full += text
                try:
                    await on_text(full)
                except Exception as exc:  # noqa: BLE001
                    log.debug("on_text callback raised: %s", exc)
            final = await stream.get_final_message()
            if final and final.usage:
                get_budget().record(model, final.usage)
    except Exception as exc:  # noqa: BLE001
        log.warning("chat_stream failed [%s: %s]", type(exc).__name__, exc)
        await on_text(full or "Streaming interrupted — try again.")


async def _ollama_chat(*, model, system, messages, tools, max_tokens):
    """Stub fallback. Returns SimpleNamespace with empty text content + 0 usage."""
    return types.SimpleNamespace(
        content=[types.SimpleNamespace(type="text", text="[ollama-stub]")],
        stop_reason="end_turn",
        usage=types.SimpleNamespace(
            input_tokens=0, output_tokens=0,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        ),
    )
