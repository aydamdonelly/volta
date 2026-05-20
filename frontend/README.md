# Volta Frontend

Next.js 15+ App Router · React 18 · TypeScript · Wave Design System · IBM Plex Sans

## Prerequisites

- Node.js 22+ and npm 10+
- Backend running on `http://localhost:8000`
  - From repo root: `LLM_REPLAY=1 .venv/bin/uvicorn backend.main:app --port 8000 --reload`

## Setup

```bash
npm install
npx playwright install chromium  # one-time, ~150 MB
```

## Run

```bash
npm run dev      # http://localhost:3000
npm run build    # production build
npm run start    # production server on :3000
```

Set `NEXT_PUBLIC_API_URL` to override the default `http://localhost:8000` backend.

## Tests

```bash
npm run test:unit   # vitest unit tests (lib/store reducer)
npm run test:e2e    # Playwright e2e (requires backend running)
```

## Structure

- `app/` — Next.js App Router (`layout.tsx`, `page.tsx`, `globals.css`)
- `components/` — UI components (Canvas, WindowManager, ChartWindow, …, VoiceTextDot, NewsTicker, ClockBar, TemplateBar, RawDataModal, EmptyCanvas)
- `lib/` — Utilities (zustand store, REST API, TZ helper, Wave chart palette, LTTB downsampling)
- `types.ts` — TypeScript types mirroring `backend/models.py`
- `public/` — Static assets (volta-logo.png, wave-tokens.css)
- `tests/e2e/` — Playwright specs

## Demo (~6 minutes)

1. `npm run dev` + backend up
2. Empty canvas: click **"Show me Germany's solar duck curve"** → 4 windows spawn (~3s)
3. Click **"Why did the German day-ahead price crash on April 5th?"** → see Apr-5 negative-price chart + Sonnet narration citing **-€16.34/MWh** with source-curve provenance
4. Click **"DK1 to SE4 cross-border spread"** → Optimeering imbalance band in counter
5. `[Step +6h]` → news events fire in ticker
6. Click ticker event → UC2 context window
7. **Save…** template, **Restore…** roundtrip

## Voice + Text

- **Voice**: press `Space` (when no input focused) → toggle Web Speech API listening (Chrome/Edge only)
- **Text**: press `/` → focus text input, type thesis, Enter
- Both paths submit to `POST /intent` and stream WS canvas-ops in <5s
