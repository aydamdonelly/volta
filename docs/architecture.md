# Architecture

## Guiding principles

- **Cache-first, always.** The demo never reads Volue live. `volue-insight-timeseries` runs only in the offline pre-pull script, never in the request path. The cache is a snapshot of real Volue responses — same numbers, just frozen on disk.
- **Grounding in code, narration in the LLM.** The fundamentals breakdown is deterministic Python. The LLM receives the numbers (with `source_curve` + `ts`) and only narrates. It cannot change a figure.
- **Thin web layer, fat data layer.** One Python process (FastAPI) owns the cache, the replay clock, the fundamentals engine, the derived-news engine, and the Anthropic orchestration. No IPC bridge, no second language.
- **Composition over inheritance.** One window component, four types via discriminated union. No plugin frameworks, no database.

## System diagram

```mermaid
flowchart TB
    subgraph FE["Frontend — Next.js App Router (one client page, local)"]
        DOT["VoiceTextDot — Web Speech API + text → submit_intent(text)"]
        CANVAS["Canvas — CSS grid, empty → themes → windows"]
        WM["WindowManager — small (1-line) ⇄ big (accordion), 4 types"]
        TICKER["NewsTicker — DerivedNews, 'context, not proof' badge"]
        CLOCK["ClockBar — virtual_now, Play / Step"]
        TPL["TemplateBar — save / restore"]
        RAW["RawDataModal — raw curve view, two clicks away"]
    end
    subgraph BE["Backend — FastAPI (Python 3.12, one process)"]
        WS["WebSocket /ws — canvas op stream"]
        REST["REST /intent /tick /template/* /curve/raw"]
        ORCH["AIOrchestrator — Anthropic tool-calling"]
        FUND["FundamentalEngine — deterministic residual decomposition"]
        NEWS["DerivedNewsEngine — forecast-delta and spike rules"]
        CLK["VirtualNowClock — D 00:00 → 15-min ticks"]
        TPLS["TemplateStore — JSON on disk"]
    end
    subgraph DATA["Data layer (offline pre-pull, then read-only)"]
        CACHE[("Parquet cache — data/cache/*.parquet")]
        PULL["prepull.py — volue-insight-timeseries + optimeering-beta"]
        PICK["pick_demo_day.py — scans the available window for the best day"]
    end
    VOLUE(["Volue Insight API — offline only"])
    LLM(["Anthropic — claude-haiku-4-5 router / claude-sonnet-4-6 narration"])
    DOT -->|POST /intent| REST --> ORCH
    ORCH <-->|tool calls| LLM
    ORCH --> FUND & NEWS & CLK & TPLS
    ORCH -->|canvas ops| WS --> CANVAS --> WM
    CLOCK -->|POST /tick| REST --> CLK --> NEWS
    NEWS -->|news event| WS --> TICKER
    TPL -->|/template/save\|restore| REST
    WM -->|/curve/raw| REST --> RAW
    FUND & NEWS & CLK & REST --> CACHE
    PULL -->|writes once| CACHE
    PICK --> CACHE
    PULL -.->|offline, before the demo| VOLUE
```

## Component responsibilities

| Component | Responsibility | Interface |
|---|---|---|
| **VoiceTextDot** | Web Speech API for live transcript; equivalent text input in the same dot; no visible chat history | `POST /intent {text, canvas_state}` |
| **Canvas** | Starts empty; themes group windows visually; windows are grid items | Consumes WS canvas-op stream |
| **WindowManager** | One component, four `type`s; `small` (1-line) ⇄ `big` (accordion); raw-data toggle | Discriminated union props; `onExpand`, `onRawData` callbacks |
| **NewsTicker** | Thin bar of `DerivedNewsEvent`s; click spawns explanation window | WS news events; click → `POST /intent {news_id}` |
| **ClockBar** | Displays `virtual_now`; Play (auto) / Step (manual, demo-safe) | `POST /tick {steps}` |
| **TemplateBar** | Save / restore named layouts | `POST /template/save\|restore` |
| **AIOrchestrator** | System prompt, tool dispatch, thesis → windows; calls code tools, narrates only; auto-attaches counter-evidence and a user-intent recommendation | In: intent / news_id + state. Out: ordered canvas ops |
| **FundamentalEngine** | Deterministic `residual = consumption − solar − wind`; spreads; min/max/negative hours; every number carries `source_curve` + `ts` | `decompose(area, t_from, t_to, virtual_now) → FundamentalBreakdown` |
| **DerivedNewsEngine** | Rule-based news from cache (forecast delta, price spike) | `events_at(virtual_now) → list[DerivedNewsEvent]` |
| **VirtualNowClock** | Starts at D 00:00; `tick(n)` advances n × 15 min; the only time source | `now()`, `tick(n)`, `reset()` |
| **TemplateStore** | Named layout snapshots as JSON | `save / restore / list` |

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js App Router, one client page, local `next dev` | Eliminates network risk on stage. Vercel is an optional post-demo deploy. |
| Charting | Recharts | Declarative, React-native, fastest time-to-chart against fixed data. |
| Window / layout | CSS grid + a small `small ↔ big` state | We tried react-grid-layout v2 and the beta had an internal setState loop. CSS grid is simpler and stable. |
| Voice | Web Speech API + text input in the same dot | No mic-on-stage failure mode. Text is an equally valid path. |
| Backend | FastAPI (Python 3.12), one process, `uvicorn`, WS + REST | Python is required for `volue-insight-timeseries`, `optimeering-beta`, and pandas. WS streams canvas ops for the "fills in live" feel. |
| Python ↔ web | Pre-baked Parquet + thin FastAPI, no Node↔Python bridge | Cleanest. |
| LLM | Router `claude-haiku-4-5`, narration `claude-sonnet-4-6`, optional ollama fallback | Two-tier keeps cost and latency in budget. |
| LLM orchestration | Anthropic tool-calling. Tools manipulate the canvas. | The LLM picks tools and parameters; truth lives in the code. |
| State / transport | WS server → canvas-op stream; REST for commands; `zustand` store on the client | Minimal. |
| Persistence | JSON files (`data/templates/`, `data/demo_day.json`) | No database needed. |

## AI orchestration

**System-prompt rules.** (1) "You manipulate a canvas through tools. You never invent numbers, prices, or causality." (2) Hard scope cut — no alpha signals, no trade suggestions; the product augments and explains. Intent recommendations only ever describe what to observe, never what to trade. (3) Grounding — fundamentals are stated only with tool-returned numbers and their source citation; news causality is always hedged. (4) Every thesis must attach exactly one counter-evidence window and one user-intent recommendation. (5) Latency discipline — minimal tool sequence; if a pre-defined layout matches, call `apply_layout` directly. (6) Output is tool calls; free text only for requested `text` / `counter` bodies.

**Tool set (Anthropic tool-calling).**

```python
TOOLS = [
  # Spawn a window in small state.
  {"name": "spawn_window", "input_schema": {"type": "object", "properties": {
     "theme": {"type": "string"},
     "window_type": {"type": "string", "enum": ["chart", "text", "news", "counter"]},
     "title": {"type": "string"}, "summary_line": {"type": "string"},
     "curve_keys": {"type": "array", "items": {"type": "string"}},
     "spec": {"type": "object"}},
     "required": ["theme", "window_type", "title", "summary_line"]},
   "returns": {"window_id": "str", "ok": "bool"}},

  # Pre-defined layout bundle for a known thesis. Fastest path; preferred.
  {"name": "apply_layout", "input_schema": {"type": "object", "properties": {
     "thesis_key": {"type": "string"},
     "theme": {"type": "string"}}, "required": ["thesis_key"]},
   "returns": {"window_ids": "list[str]", "theme": "str"}},

  # Deterministic fundamentals decomposition. The LLM does not compute numbers.
  {"name": "request_explanation", "input_schema": {"type": "object", "properties": {
     "area": {"type": "string", "enum": ["DE", "NL", "DK1", "SE4"]},
     "t_from": {"type": "string"}, "t_to": {"type": "string"},
     "focus": {"type": "string", "enum": ["price_crash", "duck_curve", "spread"]}},
     "required": ["area", "focus"]},
   "returns": {"breakdown": "FundamentalBreakdown", "narration_hint": "str"}},

  # Mandatory companion to every thesis.
  {"name": "attach_counter_evidence", "input_schema": {"type": "object", "properties": {
     "thesis_key": {"type": "string"}, "theme": {"type": "string"}},
     "required": ["thesis_key", "theme"]},
   "returns": {"window_id": "str", "points": "list[{claim, value, source_curve, ts}]"}},

  {"name": "get_derived_news", "input_schema": {"type": "object", "properties": {
     "area": {"type": "string"},
     "severity_min": {"type": "string", "enum": ["low", "med", "high"]}},
     "required": []},
   "returns": {"events": "list[DerivedNewsEvent]"}},

  {"name": "save_template", "input_schema": {"type": "object", "properties": {
     "name": {"type": "string"}}, "required": ["name"]},
   "returns": {"ok": "bool", "name": "str"}},

  {"name": "restore_template", "input_schema": {"type": "object", "properties": {
     "name": {"type": "string"}}, "required": ["name"]},
   "returns": {"ok": "bool", "canvas_state": "object"}},

  {"name": "advance_clock", "input_schema": {"type": "object", "properties": {
     "ticks": {"type": "integer"}}, "required": ["ticks"]},
   "returns": {"virtual_now": "str", "fired_news": "list[DerivedNewsEvent]"}},
]
```

**Grounding data types.** The LLM may not change a number. Every figure carries its source curve and timestamp.

```python
@dataclass
class SourcedValue:
    label: str
    value: float
    unit: str
    source_curve: str   # e.g. "rdl de ec00 mwh/h cet min15 f"
    ts: str             # the exact timestamp used

@dataclass
class FundamentalBreakdown:
    area: str
    headline: str
    drivers: list[SourcedValue]
    method_note: str    # "residual = consumption − solar − wind (deterministic)"
```

**Thesis → windows, three paths in order of preference.** (1) Pre-defined layouts for known scenarios — Haiku classifies the thesis to a `thesis_key`, then `apply_layout` spawns the bundle deterministically (well under 5 seconds). (2) Generic path for off-script questions — Sonnet emits a `spawn_window` sequence. (3) Narration — Sonnet writes the window bodies from the `FundamentalBreakdown`.

**Latency and budget.** Pre-defined layouts skip tool looping. Prompt caching covers the system prompt and tool defs. Haiku-routing separates classification from the heavier Sonnet narration. Fundamental numbers are pre-computed at cache-build time (`data/precomputed_breakdowns.json`) so `request_explanation` is a lookup in the demo path. WS streams windows incrementally. `LLM_REPLAY=1` reads recorded responses in dev for budget control; live in demo mode.

## Replay design

**Cache layout.**

```
data/cache/
  timeseries/   pri_de_spot_eur_mwh_cet_h_a.parquet      # cols: ts (UTC), value, curve_key
                pri_de_intraday_eur_mwh_cet_min15_a.parquet
                pri_nl_spot_eur_mwh_cet_h_a.parquet
                pro_de_spv_mwh_h_cet_min15_n.parquet
                cap_de_spv_mw_cet_min15_a.parquet
                pri_dk1_spot_eur_mwh_cet_h_a.parquet
                pri_se4_spot_eur_mwh_cet_h_a.parquet
  instances/    pro_de_spv_ec00_mwh_h_cet_min15_f.parquet  # cols: ts, value, issue_date, curve_key
                pro_de_wnd_ec00_mwh_h_cet_min15_f.parquet
                rdl_de_ec00_mwh_h_cet_min15_f.parquet
                con_de_ec00_mwh_h_cet_min15_f.parquet
                co2_pri_ets_eua_01_eur_eua_cet_m_f.parquet
  optimeering/  <opti_curve>.parquet                       # D−7d to D+1d
  meta/         curve_index.json                           # curve_key → file, type, unit, area
data/demo_day.json                # {date, reason, max_min_spread, neg_midday, fallback}
data/precomputed_breakdowns.json  # demo-day FundamentalBreakdowns (LLM-free at runtime)
data/llm_fixtures/                # recorded LLM responses for LLM_REPLAY
data/templates/                   # saved layout snapshots
```

Rules: time series are stored long `(ts, value, curve_key)` with UTC-tz-aware timestamps; window is D−14d to D+2d. Instances additionally have `issue_date` (multiple revisions per day, so the demo can show "the forecast was revised"). `curve_index.json` is the single lookup — no curve names hard-coded in app code; `prepull.py` does `session.search()` and writes the real name.

**The virtual-now clock.**

```python
class VirtualNowClock:
    def __init__(self, day):
        self._t0 = datetime.combine(day, time(0, 0), tzinfo=timezone.utc)
        self._cursor = self._t0

    def now(self):
        return self._cursor

    def tick(self, steps=1):
        self._cursor += timedelta(minutes=15 * steps)
        return self._cursor

    def reset(self):
        self._cursor = self._t0


def read_ts(curve_key, clock):
    df = _parquet(curve_key)
    return df[df.ts <= clock.now()]


def read_latest_instance(curve_key, clock):
    df = _parquet(curve_key)
    iss = df[df.issue_date <= clock.now()]
    return iss[iss.issue_date == iss.issue_date.max()]
```

**Derived-news rules.** (A) Forecast revision — compare the two most recent issues of solar / wind / residual-load forecasts; if `|cur − prev|.max() ≥ THRESH`, emit a news card. (B) Realised price spike — compare `pri … spot a` to a 24-hour rolling baseline; if `|last − base| ≥ PRICE_THRESH` or `last < 0`, emit a news card. The UI always renders a "context, not proof" badge.
