# Data sources

Volta pulls from three external APIs in the request path: Volue Insight, Optimeering, and Anthropic. A fourth (Firecrawl) is used for grounded news search.

## Volue Insight

European power market fundamentals — day-ahead prices, intraday prices, consumption, solar and wind production (actuals and EC00 forecasts), residual load, gas (TTF), CO2 (EUA), and weather backcasts. Auth is OAuth2 client-credentials.

**Env keys**

```
VOLUE_INSIGHT_CLIENT_ID
VOLUE_INSIGHT_CLIENT_SECRET
VOLUE_INSIGHT_API_URL=https://api.volueinsight.com
VOLUE_INSIGHT_AUTH_URL=https://auth.volueinsight.com
```

**Curve naming**

The naming convention is `<commodity> <area> [<weather-run>] <attr> <unit> <tz> <resolution> <datatype>`. Curves are looked up by name through Volue's `search()`; names are never hard-coded in product code. The set actually used is enumerated in `data/cache/meta/curve_index.json` after `scripts/prepull.py` runs.

The last token of every curve name is its data type — `a` actual, `f` forecast (an INSTANCES curve, needs `issue_date`), `n` normal (30-year weather climatology, history-free), `s` backcast, `sa` scenario. INSTANCES curves require `get_instance(issue_date=...)` or `get_latest()`; ordinary time series use `get_data(data_from=, data_to=, function=, frequency=)`.

**Reading one curve**

```python
import volue_insight_timeseries as vit
import pandas as pd

session = vit.Session(client_id=..., client_secret=...)
curve = session.get_curve(name='pri de spot €/mwh cet h a')   # DE day-ahead actual
ts = curve.get_data(data_from=pd.Timestamp('2026-03-01 00:00'),
                    data_to=pd.Timestamp('2026-03-08 00:00'))  # end date exclusive
series = ts.to_pandas()
```

`get_data` end date is exclusive — a common off-by-one. Aggregation can be pushed server-side with `function='AVERAGE'`, `frequency='H'`.

**The cache**

`scripts/prepull.py` is the only Volue contact point. It writes Parquet files into `data/cache/`. The demo reads those Parquet files — never the API. This is the snapshot-of-the-API approach: the cache contains real Volue responses, frozen for offline replay so token expiry and stage network can't break the demo.

Time series are stored in a `D−14d` to `D+2d` window around the demo day. Forecast instances are pulled for several issue dates so the "forecast was revised" derived-news rule has real revisions to detect.

## Optimeering

Imbalance, point, and quantile predictions for the Nordics (NO1, DK1, SE4) and DE (beta). Use the `optimeering-beta` package, not the older `optimeering`. Auth is an API key.

**Env keys**

```
OPTIMEERING_API_KEY
OPTIMEERING_HOST
```

**Reading**

```python
from optimeering_beta import Configuration, OptimeeringClient
client = OptimeeringClient(Configuration(api_key=os.environ['OPTIMEERING_API_KEY']))
series = client.predictions_api.list_series(area=['DK1', 'SE4'])
data = series.filter(product=['Imbalance'], statistic=['Point']).retrieve(start='-P1W')
df = data.to_pandas(unpack_value_method='new_columns')
```

`event_time` is UTC and represents the model initialisation; `prediction_for` is the start of the 15-minute target. DE imbalance is beta and live-only (no simulation history); Nordic series support `retrieve_versioned(include_simulated=True)` for backtesting.

## Anthropic

Two models. Sonnet 4.6 picks the layout and writes the narration. Haiku 4.5 routes intents into a `thesis_key`.

**Env keys**

```
ANTHROPIC_API_KEY
ANTHROPIC_MODEL=claude-sonnet-4-6
```

**Replay**

Set `LLM_REPLAY=1` to read recorded responses from `data/llm_fixtures/` instead of calling Anthropic. Used during development to control the budget. Live in demo mode.

The orchestrator uses prompt caching for the system prompt and tool definitions, and a Haiku → Sonnet two-tier so the cheap model handles classification and the expensive one only narrates.

## Firecrawl

Grounded news search. The result card always renders a `context, not proof` badge — Volta never lets the LLM speak news as if it were a fundamental.

**Env keys**

```
FIRECRAWL_API_KEY
```

## Setup

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env.local   # fill in the keys above
python scripts/prepull.py --mode=demo
```

Hard pins: Python 3.12, `pandas==2.2.3`, `volue-insight-timeseries`, `optimeering-beta`, `anthropic`, `pyarrow`. Pandas pin is forced by the three libraries' joint constraints.
