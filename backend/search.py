"""Lupe-click → real web search via Firecrawl + Sonnet reformulation.

Flow:
  1. Frontend POSTs /search/enrich with card context (curve_keys, recent values,
     virtual_now, user_text).
  2. Backend emits spawn_window(window_type="search") with empty placeholder body
     (so the user sees the card immediately, with a "searching…" spinner).
  3. Backend calls Firecrawl /v2/search with a constructed query, then hands the
     top hits + snippets to Sonnet to reformulate into 2-4 sentences with citations.
  4. Backend emits update_window with the body + citations + the actual query.

Graceful degradation: missing FIRECRAWL_API_KEY → body says "Search unavailable
(no Firecrawl API key configured)" with the constructed query echoed back.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("volta.search")

FIRECRAWL_BASE = os.environ.get("FIRECRAWL_API_BASE", "https://api.firecrawl.dev")
SEARCH_TIMEOUT_S = float(os.environ.get("SEARCH_TIMEOUT_S", "12"))
SEARCH_MAX_HITS = int(os.environ.get("SEARCH_MAX_HITS", "5"))

SYSTEM_SEARCH = (
    "You are Volta's research adjunct. The trader clicked a magnifying glass on "
    "a card in their canvas. Use the web-search results below to bring back "
    "external context that complements — never replaces — the Volue+Optimeering "
    "data shown in the card.\n\n"
    "RULES:\n"
    "- The virtual_now provided below is the trader's reference time. Treat it "
    "  as 'today'. Real-world publication dates close to virtual_now matter "
    "  more than older sources.\n"
    "- Always cite each claim by URL using markdown links: [source title](URL).\n"
    "- Hedge: 'reported by', 'as of', 'as widely cited' — never assert without a "
    "  source.\n"
    "- Reformulate findings in 2-4 sentences. Do not invent. If results are "
    "  thin / off-topic, say so explicitly: 'No fresh public coverage for this "
    "  window.'\n"
    "- The card is rendered alongside live Volue data; do not contradict the "
    "  numbers shown, only contextualize.\n"
    "- If the trader's question is in German, answer in German."
) * 2


def build_query(context: dict) -> str:
    """Build a Firecrawl /search query from card context."""
    title = context.get("title", "") or ""
    summary = context.get("summary_line", "") or ""
    curves = context.get("curve_keys") or []
    user_text = context.get("user_text", "") or ""
    virtual_now = context.get("virtual_now", "") or datetime.now(timezone.utc).isoformat()
    # Best signal first: user_text > title > summary > curves
    parts: list[str] = []
    if user_text:
        parts.append(user_text)
    elif title:
        parts.append(title)
    if curves:
        parts.append(" ".join(curves[:3]))
    if summary and summary not in parts:
        parts.append(summary)
    parts.append(virtual_now[:10])  # date hint
    return " ".join(p.strip() for p in parts if p.strip())[:300]


async def firecrawl_search(query: str, *, limit: int = SEARCH_MAX_HITS) -> list[dict]:
    """Call Firecrawl /v2/search. Returns list of {url, title, description, markdown?}."""
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        return []
    url = f"{FIRECRAWL_BASE}/v2/search"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"query": query, "limit": limit}
    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT_S) as client:
            r = await client.post(url, headers=headers, json=body)
            if r.status_code >= 400:
                log.warning("firecrawl /search %s: %s", r.status_code, r.text[:200])
                return []
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("firecrawl /search failed: %s", exc)
        return []

    # Firecrawl v2 returns {success: true, data: {web: [...]}} OR {success: true, data: [...]}
    web = []
    if isinstance(data, dict):
        d = data.get("data") or data.get("results") or []
        if isinstance(d, dict):
            web = d.get("web") or d.get("results") or []
        elif isinstance(d, list):
            web = d
    hits: list[dict] = []
    for item in web[:limit]:
        if not isinstance(item, dict):
            continue
        hits.append({
            "url": item.get("url") or item.get("link") or "",
            "title": item.get("title") or item.get("name") or "",
            "description": item.get("description") or item.get("snippet") or "",
            "markdown": item.get("markdown") or item.get("content") or "",
        })
    return hits


def format_hits_for_prompt(hits: list[dict], max_chars_per_hit: int = 600) -> str:
    if not hits:
        return "(no web results)"
    lines: list[str] = []
    for i, h in enumerate(hits, start=1):
        snippet = (h.get("markdown") or h.get("description") or "").strip()
        if len(snippet) > max_chars_per_hit:
            snippet = snippet[:max_chars_per_hit] + "…"
        lines.append(f"[{i}] {h.get('title', '(untitled)')} — {h.get('url', '')}\n{snippet}")
    return "\n\n".join(lines)


async def reformulate(hits: list[dict], context: dict) -> str:
    """Ask Sonnet to reformulate the web results in 2-4 sentences with citations."""
    from backend.llm import chat

    user_prompt = (
        f"Trader is viewing a {context.get('window_type', '?')} card titled "
        f"\"{context.get('title', '')}\".\n"
        f"Summary line: {context.get('summary_line', '')}\n"
        f"Curves on the card: {context.get('curve_keys', [])}\n"
        f"virtual_now: {context.get('virtual_now', '')}\n"
        f"Trader asked: {context.get('user_text', '(no extra question)')!r}\n\n"
        f"Web search results:\n{format_hits_for_prompt(hits)}\n\n"
        "Reformulate the most relevant findings in 2-4 sentences with inline citations "
        "[title](URL). If results are thin, say 'No fresh public coverage for this window.'"
    )

    try:
        r = await asyncio.wait_for(
            chat(
                model="claude-sonnet-4-6",
                system=SYSTEM_SEARCH,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=600,
                fixture_key=None,
                force_live=True,
            ),
            timeout=SEARCH_TIMEOUT_S,
        )
        for blk in r.content:
            if getattr(blk, "type", None) == "text":
                return (blk.text or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("search reformulate failed: %s", exc)
    return ""


async def enrich(
    search_id: str,
    request: dict,
    *,
    manager,
    clock,
) -> None:
    """Fire-and-stream: emit spawn_window placeholder, then patch with the result."""
    context = request.get("context") or {}
    window_id_src = request.get("window_id") or ""
    intent_id = request.get("intent_id") or search_id

    query = build_query(context)
    # Land the new search card INSIDE the source card's theme. Frontend
    # reducer auto-stubs the theme if it doesn't yet exist (e.g. when search
    # is the first thing on a fresh canvas).
    theme_id = request.get("theme_id") or "theme_search"
    new_window_id = f"win_search_{uuid.uuid4().hex[:8]}"

    placeholder = {
        "window_id": new_window_id,
        "theme_id": theme_id,
        "window_type": "search",
        "title": f"🔍 {context.get('title', 'Web search')}",
        "summary_line": f"Searching: {query[:120]}",
        "state": "small",
        "curve_keys": list(context.get("curve_keys") or []),
        "spec": {
            "body": "Searching the web…",
            "query": query,
            "badge": "web_search",
            "dismissable": True,
            "hedged": True,
            "citations": [],
            "related_curve_keys": list(context.get("curve_keys") or []),
            "related_window_id": window_id_src,
        },
        "grounding": None,
        "raw_toggle": False,
        "intent_id": intent_id,
    }
    # NO spawn_theme — frontend appends to existing theme or auto-stubs.
    await manager.emit("spawn_window", placeholder)

    hits = await firecrawl_search(query)
    if not os.environ.get("FIRECRAWL_API_KEY"):
        body = (
            "Search unavailable — FIRECRAWL_API_KEY not set on the backend. "
            f"Query that would have run: `{query}`."
        )
        citations: list[dict] = []
    else:
        body = await reformulate(hits, context)
        if not body:
            body = "No fresh public coverage for this window."
        citations = [
            {
                "url": h["url"],
                "title": h.get("title") or h["url"],
                "accessed_at": datetime.now(timezone.utc).isoformat(),
                "snippet": (h.get("description") or "")[:240],
            }
            for h in hits
            if h.get("url")
        ]

    await manager.emit(
        "update_window",
        {
            "window_id": new_window_id,
            "patch": {"body": body, "citations": citations, "query": query},
            "intent_id": intent_id,
        },
    )
