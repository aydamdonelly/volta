# What's real and what's not

A short disclosure of which numbers, calls, and behaviours in Volta are live versus replayed.

## Real

- **Volue Insight prices and fundamentals** for the demo day window. Pulled once via `scripts/prepull.py`, written to `data/cache/*.parquet`, and read from disk during the demo. The cache contains the same numbers Volue returned at pull time — it's a snapshot of the same API, not fixture data.
- **Optimeering imbalance forecasts** for NO1, DK1, SE4. Same pattern: pulled offline, cached, served from disk.
- **Anthropic streaming narration.** Claude Sonnet 4.6 narrates and picks the layout; Claude Haiku 4.5 routes intents. When `LLM_REPLAY=0` (the demo default), every narration is a live Anthropic call against a real cache hit on the system prompt and tool definitions.
- **Firecrawl-grounded news search.** Live, every time. The result card always wears a `context, not proof` badge.

## Cached, not faked

The Parquet cache is not fixture data. It contains the actual responses Volue returned when `prepull.py` ran. The point is to avoid token expiry and network flakiness on stage, not to fabricate the demo. If you re-run `prepull.py` with fresh credentials you'll get the same shape of data, on the same curves, for the same window.

## Fixtures (for development, off by default)

- **`LLM_REPLAY=1`** swaps live Anthropic calls for recorded responses in `data/llm_fixtures/`. We use this during development to control the API budget. Demo mode is `LLM_REPLAY=0`.
- **`scripts/pick_demo_day.py`** scans the cache for the most narratively useful day (largest intraday spread, deepest negative midday) and writes `data/demo_day.json`. The choice is the script's, not ours.

## The grounding contract

The fundamentals breakdown — `residual = consumption − solar − wind`, daily mean, intraday min and max, hours of negative prices — is computed in Python from the cached time series. The LLM receives those numbers along with the source curve name and the exact timestamp, and is not permitted to change them. Every figure Volta says is traceable to one row of one Parquet file.

That's the line: when Volta states a price, it queried the cache. When it explains *why*, that explanation is Sonnet writing prose around numbers it didn't invent.
