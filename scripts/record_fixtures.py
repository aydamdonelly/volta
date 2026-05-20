"""Record live Anthropic fixtures. Cost ~$0.10. Sets LLM_REPLAY=0 LLM_RECORD=1.

Outputs 6 files to data/llm_fixtures/:
  haiku__apply_layout__de_duck_curve__v1.json
  haiku__apply_layout__de_price_crash__v1.json
  haiku__apply_layout__dk1_se4_spread__v1.json
  sonnet__narration__de_duck_curve_breakdown__v1.json
  sonnet__narration__de_price_crash_breakdown__v1.json
  sonnet__narration__dk1_se4_spread_breakdown__v1.json
"""
from __future__ import annotations
import asyncio, hashlib, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env.local")

os.environ["LLM_REPLAY"] = "0"
os.environ["LLM_PROVIDER"] = "anthropic"

from anthropic import AsyncAnthropic

FIXTURES_DIR = ROOT / "data" / "llm_fixtures"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_HAIKU = (
    "You are Volta, an energy trader's copilot. Use the apply_layout tool to map a "
    "trader's verbal thesis to ONE of the predefined demo layouts. "
    "Allowed thesis_key values: de_duck_curve, de_price_crash, dk1_se4_spread. "
    "Never invent numbers. Choose the closest semantic match."
)
SYSTEM_SONNET = (
    "You are Volta narrating a fundamental breakdown to an energy trader. "
    "Be concise (2-3 sentences). ALWAYS cite the source_curve and ts inline in parentheses. "
    "NEVER invent numbers — only repeat values from the provided breakdown JSON. "
    "Use € symbol and CET awareness. Hedge with 'context' when appropriate."
)

THESIS_TEXTS = {
    "de_duck_curve":   "I want to trade Germany's solar duck curve — show me solar generation, residual demand, and the afternoon price.",
    "de_price_crash":  "Why did the German day-ahead price crash to negative levels on April 5th, 2026?",
    "dk1_se4_spread":  "Show me the DK1 to SE4 cross-border spread and the imbalance prediction for the Nordic side.",
}

TOOLS = [{
    "name": "apply_layout",
    "description": "Apply the predefined layout for a known thesis. Fast path.",
    "input_schema": {
        "type": "object",
        "properties": {
            "thesis_key": {"type": "string", "enum": ["de_duck_curve", "de_price_crash", "dk1_se4_spread"]},
            "theme": {"type": "string", "description": "Display title for the theme section"},
        },
        "required": ["thesis_key", "theme"],
    },
}]

NARRATION_INPUTS = {
    "de_duck_curve": {
        "area": "DE", "focus": "duck_curve",
        "headline": "DE solar duck-curve: midday solar peak vs winter consumption",
        "drivers": [
            {"label": "Day-Ahead price (daily avg)", "value": 125.09, "unit": "€/MWh", "source_curve": "pri de spot €/mwh cet h a", "ts": "2026-03-06T23:00:00+00:00"},
            {"label": "Solar generation (daily avg)", "value": 14994.0, "unit": "MWh/h", "source_curve": "pro de spv mwh/h cet min15 a", "ts": "2026-03-06T23:45:00+00:00"},
            {"label": "Wind generation (daily avg)", "value": 5635.0, "unit": "MWh/h", "source_curve": "pro de wnd mwh/h cet min15 a", "ts": "2026-03-06T23:45:00+00:00"},
            {"label": "Consumption (daily avg)", "value": 60852.0, "unit": "MWh/h", "source_curve": "con de mwh/h cet min15 a", "ts": "2026-03-06T23:45:00+00:00"},
            {"label": "Residual demand (computed)", "value": 40223.0, "unit": "MWh/h", "source_curve": "con − spv − wnd", "ts": "2026-03-06T23:45:00+00:00"},
        ],
        "method_note": "All drivers from Volue Insight cache. Residual = con - spv - wnd verified vs rdl curve.",
        "residual_check_ok": True,
    },
    "de_price_crash": {
        "area": "DE", "focus": "price_crash",
        "headline": "DE Mar-6 price avg daily mean €125.09/MWh — tight supply",
        "drivers": [
            {"label": "Day-Ahead price (daily avg)", "value": 125.09, "unit": "€/MWh", "source_curve": "pri de spot €/mwh cet h a", "ts": "2026-03-06T23:00:00+00:00"},
            {"label": "Wind generation (daily avg)", "value": 5635.0, "unit": "MWh/h", "source_curve": "pro de wnd mwh/h cet min15 a", "ts": "2026-03-06T23:45:00+00:00"},
            {"label": "Consumption (daily avg)", "value": 60852.0, "unit": "MWh/h", "source_curve": "con de mwh/h cet min15 a", "ts": "2026-03-06T23:45:00+00:00"},
            {"label": "Residual demand (computed)", "value": 40223.0, "unit": "MWh/h", "source_curve": "con − spv − wnd", "ts": "2026-03-06T23:45:00+00:00"},
            {"label": "Gas TTF front-month", "value": 39.71, "unit": "€/MWh", "source_curve": "gas pri nl ttf fut front-month clo spectron €/mwh cet d a", "ts": "2026-03-06T23:00:00+00:00"},
        ],
        "method_note": "All drivers from Volue Insight cache. Residual = con - spv - wnd verified vs rdl curve.",
        "residual_check_ok": True,
    },
    "dk1_se4_spread": {
        "area": "DK1", "focus": "spread",
        "headline": "DK1 ↔ SE4 cross-border spread on Mar-6 with Nordic Imbalance context",
        "drivers": [
            {"label": "DK1 DA price (daily avg)", "value": 91.49, "unit": "€/MWh", "source_curve": "pri dk1 spot €/mwh cet h a", "ts": "2026-03-06T23:00:00+00:00"},
        ],
        "method_note": "DK1 spot from Volue; imbalance from Optimeering NO1/DK1/SE4 series.",
        "residual_check_ok": True,
    },
}


def _serialize_response(r) -> dict:
    """Convert Anthropic SDK Message to plain dict per fixture spec."""
    content = []
    for blk in r.content:
        if blk.type == "tool_use":
            content.append({"type": "tool_use", "id": blk.id, "name": blk.name, "input": blk.input})
        elif blk.type == "text":
            content.append({"type": "text", "text": blk.text})
    usage = {}
    for fld in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
        usage[fld] = getattr(r.usage, fld, 0) or 0
    return {"stop_reason": r.stop_reason, "content": content, "usage": usage}


def _input_hash(messages, system) -> str:
    payload = json.dumps({"messages": messages, "system": system}, sort_keys=True)
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _save(fixture_key: str, model: str, system, messages, response_dict: dict) -> Path:
    path = FIXTURES_DIR / f"{fixture_key}.json"
    payload = {
        "fixture_key": fixture_key,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "input_hash": _input_hash(messages, system),
        "response": response_dict,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


async def record_haiku(thesis_key: str, client: AsyncAnthropic) -> dict:
    text = THESIS_TEXTS[thesis_key]
    messages = [{"role": "user", "content": text}]
    system = [{"type": "text", "text": SYSTEM_HAIKU, "cache_control": {"type": "ephemeral"}}]
    r = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=256,
        system=system,
        tools=TOOLS,
        tool_choice={"type": "tool", "name": "apply_layout", "disable_parallel_tool_use": True},
        messages=messages,
    )
    d = _serialize_response(r)
    p = _save(f"haiku__apply_layout__{thesis_key}__v1", "claude-haiku-4-5", system, messages, d)
    print(f"  recorded {p.name}: stop={d['stop_reason']} tokens_in={d['usage']['input_tokens']} cache_read={d['usage']['cache_read_input_tokens']}")
    return d["usage"]


async def record_sonnet_for_thesis(thesis_key: str, client: AsyncAnthropic) -> dict:
    breakdown = NARRATION_INPUTS[thesis_key]
    user_msg = (
        "Narrate this fundamental breakdown in 2-3 sentences. Cite source_curve and ts inline. "
        f"Never invent numbers.\n\nBreakdown:\n{json.dumps(breakdown, ensure_ascii=False)}"
    )
    messages = [{"role": "user", "content": user_msg}]
    system = [{"type": "text", "text": SYSTEM_SONNET, "cache_control": {"type": "ephemeral"}}]
    r = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=system,
        messages=messages,
    )
    d = _serialize_response(r)
    p = _save(f"sonnet__narration__{thesis_key}_breakdown__v1", "claude-sonnet-4-6", system, messages, d)
    print(f"  recorded {p.name}: tokens_in={d['usage']['input_tokens']} tokens_out={d['usage']['output_tokens']}")
    return d["usage"]


async def main():
    client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Verified prices
    from backend.llm import PRICE
    total_usd = 0.0

    for tk in ["de_duck_curve", "de_price_crash", "dk1_se4_spread"]:
        u = await record_haiku(tk, client)
        p = PRICE["claude-haiku-4-5"]
        total_usd += (
            u["input_tokens"] * p["input"]
            + u["output_tokens"] * p["output"]
            + u.get("cache_creation_input_tokens", 0) * p["cache_write"]
            + u.get("cache_read_input_tokens", 0) * p["cache_read"]
        ) / 1_000_000

    for tk in ["de_duck_curve", "de_price_crash", "dk1_se4_spread"]:
        u = await record_sonnet_for_thesis(tk, client)
        p = PRICE["claude-sonnet-4-6"]
        total_usd += (
            u["input_tokens"] * p["input"]
            + u["output_tokens"] * p["output"]
            + u.get("cache_creation_input_tokens", 0) * p["cache_write"]
            + u.get("cache_read_input_tokens", 0) * p["cache_read"]
        ) / 1_000_000

    print(f"\nTotal cost: ${total_usd:.4f}")
    assert total_usd < 0.30, f"cost too high: ${total_usd:.4f}"


if __name__ == "__main__":
    asyncio.run(main())
