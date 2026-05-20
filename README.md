# Volta

A voice-driven canvas for European power markets.

![Volta composing a four-window layout that explains the DE spot price on March 6th, 2026](docs/screenshots/02-composed-layout.png)

## What this is

Energy analysts open four dashboards to explain one price spike. They tab between Volue Insight, Optimeering, news terminals, and a spreadsheet, write a paragraph that summarises what they just learned, and move on to the next question. Volta replaces that loop with a sentence.

You say *"why did DE spot crash on March 6 afternoon?"*. Volta picks the windows that answer the question — solar and wind actuals against the price curve, residual load with the EC00 forecast revision, a counter-evidence panel on gas and CO2, a final read — composes them on an empty canvas, and starts narrating while the data is loading. And the answer doesn't agree with the question: the day-ahead mean for German power on **2026-03-06 was €125.09/MWh, ranging from €48.65 to €229.55** across the day, with **15 GW of solar and 5.6 GW of wind leaving 40 GW of residual demand**. Elevated, not crashed. Volta knows because it queried the Volue cache, not because we wrote it down.

## Three things it does

![Compose: a sentence becomes a four-window layout, complete with counter-evidence and a final read](docs/screenshots/02-composed-layout.png)
*Compose: a sentence becomes a layout.*

![Search: the magnifier icon pins grounded news above the data with a 'context, not proof' label](docs/screenshots/05-search-card.png)
*Search: grounded news pinned next to the data.*

![Edit: 'remove the gas TTF chart and add a wind forecast' swaps the panels in place](docs/screenshots/04-natural-language-edit.png)
*Edit: natural language rearranges what's on the canvas.*

## Under the hood

The backend is a single FastAPI process. It owns the Volue Insight cache, the Optimeering forecast cache, the deterministic fundamentals engine, and the Anthropic orchestration. Claude Sonnet 4.6 narrates and picks the layout; Claude Haiku 4.5 routes intents. Every number Volta says carries a `source_curve` and a timestamp, so the LLM cannot drift off-anchor.

The frontend is one Next.js 15 page. Voice is the browser's native Web Speech API, with a text input in the same dot — no microphone-on-strange-stage failure mode. Charts are Recharts; the canvas is CSS grid.

## Run it locally

```bash
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env.local            # fill in Volue + Optimeering + Anthropic keys
python scripts/prepull.py --mode=demo
make api                              # FastAPI on :8000
cd frontend && npm install && npm run dev   # Next on :3000
```

Then open `localhost:3000` and start with `/` to type or `Space` to talk.

## What's real vs cached

Real: Volue Day-Ahead prices for the demo day window; Optimeering imbalance forecasts for NO1, DK1, SE4; Anthropic streaming narration; Firecrawl-grounded news search. The Volue Parquet cache in `data/cache/` is a snapshot of the same API, frozen before the demo so token expiry and stage network can't break it. The cache is not fixture data — it's what Volue returned, written to disk. The full disclosure is in [`docs/what-is-real.md`](docs/what-is-real.md).

## What we'd build next

The fundamentals engine knows residual load deterministically; the LLM never invents a number. The next step is to feed it CO₂ allowance prices and gas-marginal-plant pricing so it can narrate *why* a spread was what it was, not just *what* it was — turning grounded description into grounded explanation.

---

Built at the Volue Hackathon Amsterdam, 2026. Bastian Lipka, Seihan Kahirov, Adam Kahirov.
