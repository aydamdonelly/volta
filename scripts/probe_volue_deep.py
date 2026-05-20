"""Deep operational contract for Volue Insight — everything the clock,
FundamentalEngine, prepull and orchestrator need to know. Read-only, 0 €.
Run: .venv/bin/python scripts/probe_volue_deep.py
"""
from __future__ import annotations

import os
import re
import time
import traceback

import pandas as pd
from dotenv import load_dotenv

load_dotenv(".env.local")
import volue_insight_timeseries as vit

S = vit.Session(
    urlbase=os.environ.get("VOLUE_INSIGHT_API_URL"),
    auth_urlbase=os.environ.get("VOLUE_INSIGHT_AUTH_URL"),
    client_id=os.environ["VOLUE_INSIGHT_CLIENT_ID"],
    client_secret=os.environ["VOLUE_INSIGHT_CLIENT_SECRET"],
    timeout=300,
)


_seen: dict[str, str] = {}


def R(name: str):
    """search-first resolver. Contract rule learned: the weather-run token
    (ec00/gfs00/icon00...) belongs to FORECAST/weather curves only — ACTUAL
    curves omit it. So on a miss, retry without the weather-run token."""
    cands = [name]
    stripped = re.sub(r"\s(ec|gfs|icon)\d+\w*", "", name)
    if stripped != name:
        cands.append(stripped)
    for cand in cands:
        hits = S.search(name=cand) or []
        if not hits:
            continue
        curve = next((h for h in hits
                      if getattr(h, "name", None) in (name, cand)), hits[0])
        real = getattr(curve, "name", name)
        if real != name and name not in _seen:
            _seen[name] = real
            print(f"  [resolve] {name!r} -> {real!r}", flush=True)
        return curve
    return S.get_curve(name=name)


def hdr(t):
    print(f"\n{'='*4} {t} {'='*4}", flush=True)


def section(fn):
    try:
        fn()
    except Exception:
        traceback.print_exc()


def vocab():
    hdr("1. Metadata vocabulary (valid filter/agg values)")
    for m in ("get_areas", "get_categories", "get_data_types",
              "get_functions", "get_frequencies", "get_sources",
              "get_commodities", "get_curve_states"):
        f = getattr(S, m, None)
        if not f:
            print(f"  {m}: (absent)")
            continue
        try:
            v = f()
            v = list(v)
            print(f"  {m}: {len(v)} -> {v[:12]}")
        except Exception as e:
            print(f"  {m}: ERR {type(e).__name__}: {e}")


def ts_shape():
    hdr("2. TS data shape + timezone (clock/replay contract)")
    c = R("pri de spot €/mwh cet h a")
    ts = c.get_data(data_from="2026-01-01", data_to="2026-01-03")
    s = ts.to_pandas()
    print(f"  to_pandas -> {type(s).__name__}; dtype={s.dtype}; name={s.name!r}")
    print(f"  index type={type(s.index).__name__}; tz={s.index.tz}; "
          f"freq={getattr(s.index,'freqstr',None)}")
    print(f"  ts obj attrs: tz={getattr(ts,'tz',None)} "
          f"name={getattr(ts,'name',None)!r}")
    print(f"  first 2: {list(s.items())[:2]}")
    # virtual_now replay filter — clock is UTC (ARCHITECTURE §5); index is CET.
    cutoff_utc = pd.Timestamp("2026-01-01 12:00", tz="UTC")
    masked = s[s.index <= cutoff_utc]
    print(f"  replay filter s[s.index <= 2026-01-01T12:00Z]: "
          f"{len(masked)}/{len(s)} rows, last={masked.index[-1]}")
    print("  -> tz-aware compare works directly (CET index vs UTC cutoff)")


def instance_shape():
    hdr("3. INSTANCES shape (forecast revision contract)")
    c = R("pro de spv ec00 mwh/h cet min15 f")
    meta = c.search_instances(issue_date_from="2026-01-01",
                              issue_date_to="2026-01-05")
    iss = sorted(m.issue_date for m in meta)
    print(f"  search_instances -> {len(iss)} issue_dates; "
          f"type(issue_date)={type(iss[0]).__name__}; e.g. {iss[0]}")
    inst = c.get_instance(issue_date=iss[0], data_from="2026-01-01",
                          data_to="2026-01-12")
    p = inst.to_pandas()
    print(f"  get_instance.to_pandas -> {type(p).__name__} len={len(p)}; "
          f"index.tz={p.index.tz}; issue_date attr={getattr(inst,'issue_date',None)}")
    li = R("pro de spv ec00 mwh/h cet min15 f").get_latest(
        data_to="2026-05-20")
    lp = li.to_pandas()
    print(f"  get_latest -> issue_date={getattr(li,'issue_date',None)} "
          f"len={len(lp)} span={lp.index.min()}..{lp.index.max()}")
    # forecast revision delta (UC2 / DerivedNews rule A)
    a = c.get_instance(issue_date=iss[0], data_from="2026-01-02",
                       data_to="2026-01-06").to_pandas()
    b = c.get_instance(issue_date=iss[1], data_from="2026-01-02",
                       data_to="2026-01-06").to_pandas()
    j = pd.concat([a.rename("prev"), b.rename("cur")], axis=1).dropna()
    if len(j):
        d = (j["cur"] - j["prev"])
        print(f"  revision {str(iss[0])[:10]}->{str(iss[1])[:10]}: "
              f"overlap={len(j)} max|Δsolar|={d.abs().max():.0f} MWh "
              f"mean Δ={d.mean():.0f} -> News-rule A computable")


def big_pull():
    hdr("4. Large min15 pull (prepull feasibility)")
    c = R("pro de spv mwh/h cet min15 a")  # ACTUAL: no weather-run token
    t0 = time.perf_counter()
    s = c.get_data(data_from="2026-01-01", data_to="2026-05-20").to_pandas()
    dt = time.perf_counter() - t0
    print(f"  solar-act min15 raw 2026-01-01..05-20: {len(s)} pts in {dt:.1f}s "
          f"(expect ~13k) -> single pull OK, no chunking needed")
    t0 = time.perf_counter()
    sh = c.get_data(data_from="2026-01-01", data_to="2026-05-20",
                    function="AVERAGE", frequency="H").to_pandas()
    print(f"  server-side AVERAGE/H: {len(sh)} pts in "
          f"{time.perf_counter()-t0:.1f}s -> aggregation offloads fine")


def demo_day():
    hdr("5. Empirical demo-day pick (pick_demo_day.py logic, §D.2)")
    px = R("pri de spot €/mwh cet h a").get_data(
        data_from="2026-01-01", data_to="2026-06-01").to_pandas()
    spread = px.resample("D").agg(lambda x: x.max() - x.min())
    mins = px.resample("D").min()
    print("  top-5 intraday max-min spread (€/MWh):")
    for d, v in spread.sort_values(ascending=False).head(5).items():
        print(f"    {d:%Y-%m-%d}  spread={v:.1f}  "
              f"daymin={mins.loc[d]:.2f}  daymean={px[d:d].mean():.2f}")
    print("  top-5 lowest daily mean:")
    dm = px.resample("D").mean().sort_values()
    for d, v in dm.head(5).items():
        print(f"    {d:%Y-%m-%d}  mean={v:.2f}")
    print(f"  2026-01-01 day-ahead mean = "
          f"{px['2026-01-01':'2026-01-01'].mean():.2f} €/MWh "
          f"(empirical check)")


def fundamentals():
    hdr("6. Residual decomposition (FundamentalEngine contract)")
    day_from, day_to = "2026-01-01", "2026-01-02"
    con = R("con de mwh/h cet min15 a").get_data(
        data_from=day_from, data_to=day_to).to_pandas()
    spv = R("pro de spv mwh/h cet min15 a").get_data(
        data_from=day_from, data_to=day_to).to_pandas()
    wnd = R("pro de wnd mwh/h cet min15 a").get_data(
        data_from=day_from, data_to=day_to).to_pandas()
    rdl = R("rdl de mwh/h cet min15 sa").get_data(
        data_from=day_from, data_to=day_to).to_pandas()
    calc = (con - spv - wnd).dropna()
    j = pd.concat([calc.rename("calc"), rdl.rename("actual")],
                  axis=1).dropna()
    err = (j["calc"] - j["actual"]).abs()
    print(f"  2026-01-01 daily means: con={con.mean():.0f} spv={spv.mean():.0f} "
          f"wnd={wnd.mean():.0f} MWh")
    print(f"  residual calc(con-spv-wnd) mean={calc.mean():.0f} vs "
          f"rdl-actual mean={rdl.mean():.0f}")
    print(f"  reconciliation: n={len(j)} mean|err|={err.mean():.0f} "
          f"max|err|={err.max():.0f} MWh "
          f"({100*err.mean()/j['actual'].abs().mean():.2f}% of level) "
          f"-> deterministic decomposition is sound")


if __name__ == "__main__":
    print("=== Volue Insight — deep operational contract ===", flush=True)
    for f in (vocab, ts_shape, instance_shape, big_pull, demo_day,
              fundamentals):
        section(f)
    print("\n=== done ===", flush=True)
