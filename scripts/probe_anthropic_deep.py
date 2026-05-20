"""Deep operational contract for Anthropic — both models, tool-calling exactly
as ARCHITECTURE §4 needs it, and prompt-caching (the €200-budget lever).
Makes a FEW small real calls (~cents). Run:
  .venv/bin/python scripts/probe_anthropic_deep.py
"""
from __future__ import annotations

import os
import traceback

import anthropic
from dotenv import load_dotenv

load_dotenv(".env.local")
CLIENT = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
HAIKU = "claude-haiku-4-5"      # router (ARCHITECTURE §3)
SONNET = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")  # narration

cost_in = cost_out = 0


def acct(u):
    global cost_in, cost_out
    cost_in += getattr(u, "input_tokens", 0) + \
        getattr(u, "cache_creation_input_tokens", 0) + \
        getattr(u, "cache_read_input_tokens", 0)
    cost_out += getattr(u, "output_tokens", 0)


def hdr(t):
    print(f"\n{'='*4} {t} {'='*4}", flush=True)


def both_models():
    hdr("1. Both model IDs valid (router + narration)")
    for tag, m in (("router", HAIKU), ("narration", SONNET)):
        try:
            r = CLIENT.messages.create(
                model=m, max_tokens=8,
                messages=[{"role": "user", "content": "Reply: ok"}])
            acct(r.usage)
            txt = "".join(b.text for b in r.content if b.type == "text")
            print(f"  [{tag}] {m}: {txt.strip()!r} "
                  f"in={r.usage.input_tokens} out={r.usage.output_tokens}")
        except Exception as e:
            print(f"  [{tag}] {m}: ERR {type(e).__name__}: {e}")


# Tool set mirrors ARCHITECTURE §4 (subset).
TOOLS = [
    {"name": "apply_layout",
     "description": "Spawn the predefined window bundle for a known thesis.",
     "input_schema": {"type": "object", "properties": {
         "thesis_key": {"type": "string",
                        "enum": ["de_duck_curve", "de_newyear_crash",
                                 "dk1_se4_spread"]},
         "theme": {"type": "string"}},
         "required": ["thesis_key"]}},
    {"name": "request_explanation",
     "description": "Deterministic fundamental decomposition (LLM never computes).",
     "input_schema": {"type": "object", "properties": {
         "area": {"type": "string", "enum": ["DE", "NL", "DK1", "SE4"]},
         "focus": {"type": "string",
                   "enum": ["price_crash", "duck_curve", "spread"]}},
         "required": ["area", "focus"]}},
]
SYS_RULES = (
    "You manipulate a canvas via tools and NEVER invent numbers, prices or "
    "causality. Hard scope cut: no alpha/buy-sell signals — augment and "
    "explain only. For a known thesis prefer apply_layout (fastest path). "
    "Fundamentals are affirmative only via tool numbers; news causality is "
    "always hedged. Output only tool calls.")


def tool_calling():
    hdr("2. Tool-calling round trip (orchestrator §4 path, Haiku router)")
    stage_thesis = ("I want to trade Germany's solar duck curve: buy the "
                    "midday solar glut, sell into the evening ramp. Show me "
                    "everything I need to watch this.")
    try:
        r = CLIENT.messages.create(
            model=HAIKU, max_tokens=256,
            system=SYS_RULES, tools=TOOLS,
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": stage_thesis}])
        acct(r.usage)
        tu = [b for b in r.content if b.type == "tool_use"]
        for b in tu:
            print(f"  tool_use: {b.name}({b.input}) stop={r.stop_reason}")
        ok = any(b.name == "apply_layout"
                 and b.input.get("thesis_key") == "de_duck_curve"
                 for b in tu)
        print(f"  -> router correctly classified to de_duck_curve: {ok}")
    except Exception as e:
        print(f"  ERR {type(e).__name__}: {e}")
        traceback.print_exc()


def prompt_caching():
    hdr("3. Prompt caching (€200-budget lever)")
    # Haiku min cacheable = 2048 tok; build a realistic large system prompt.
    big = SYS_RULES + "\n\n" + ("Operational reference. " + " ".join(
        f"Rule {i}: predefined layouts beat generic spawn; cite every number "
        f"with source_curve+ts; counter-evidence is its own window; news is "
        f"context not proof." for i in range(220)))
    sys_block = [{"type": "text", "text": big,
                  "cache_control": {"type": "ephemeral"}}]
    msg = [{"role": "user", "content": "Reply with one word: ready"}]
    try:
        r1 = CLIENT.messages.create(model=HAIKU, max_tokens=8,
                                    system=sys_block, messages=msg)
        acct(r1.usage)
        r2 = CLIENT.messages.create(model=HAIKU, max_tokens=8,
                                    system=sys_block, messages=msg)
        acct(r2.usage)
        print(f"  call1: cache_create={r1.usage.cache_creation_input_tokens} "
              f"cache_read={r1.usage.cache_read_input_tokens} "
              f"in={r1.usage.input_tokens}")
        print(f"  call2: cache_create={r2.usage.cache_creation_input_tokens} "
              f"cache_read={r2.usage.cache_read_input_tokens} "
              f"in={r2.usage.input_tokens}")
        hit = r2.usage.cache_read_input_tokens > 0
        print(f"  -> cache HIT on call2: {hit} "
              f"(~90% input cost saved on repeated system prompt)")
    except Exception as e:
        print(f"  ERR {type(e).__name__}: {e}")


if __name__ == "__main__":
    print("=== Anthropic — deep operational contract ===", flush=True)
    for f in (both_models, tool_calling, prompt_caching):
        try:
            f()
        except Exception:
            traceback.print_exc()
    # rough claude-haiku-4-5 pricing ~$1/Mtok in, $5/Mtok out
    est = cost_in / 1e6 * 1.0 + cost_out / 1e6 * 5.0
    print(f"\n=== done; tokens in≈{cost_in} out≈{cost_out} "
          f"(rough ≈ ${est:.4f}, ≪ €200 budget) ===", flush=True)
