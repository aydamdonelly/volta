"""Coverage probe — verifies EVERY curve the locked plan needs (VOLUE_DATA
§B/§C) is reachable AND returns 2026 data, exercising both read paths:
  TIME_SERIES  -> get_data
  INSTANCES    -> get_instance over the planned issue_dates (UC2 revision)
Plus one real Optimeering retrieve() (not just list).

Mandates session.search() first (names vary — plan rule). Read-only on
.env.local. 0 € (no LLM). Run: .venv/bin/python scripts/coverage_probe.py
"""
from __future__ import annotations

import os
import sys

import pandas as pd
from dotenv import load_dotenv

load_dotenv(".env.local")

DEMO_DAY = "2026-01-01"
TODAY = "2026-05-19"
# Real issue_dates are discovered via search_instances (NOT hardcoded — the
# §B "06:00" assumption is wrong; this dataset issues at 00:00 CET).
# Optimeering DE-Imbalance empty + Temp backcast example-name are EXPECTED per
# the locked plan (VOLUE_DATA §E), not real failures.
EXPECTED_EMPTY = {"Opti DE Imb", "Temp backcast"}

# (label, documented search name)  — type is read at runtime, not trusted.
CURVES = [
    ("DA spot DE",        "pri de spot €/mwh cet h a"),
    ("DA spot NL",        "pri nl spot €/mwh cet h a"),
    ("DA spot BE",        "pri be spot €/mwh cet h a"),
    ("DA spot DK1 (fb)",  "pri dk1 spot €/mwh cet h a"),
    ("DA spot SE4 (fb)",  "pri se4 spot €/mwh cet h a"),
    ("Intraday DE 15m",   "pri de intraday €/mwh cet min15 a"),
    ("DA DE 15m",         "pri de spot €/mwh cet min15 a"),
    ("Residual act DE",   "rdl de ec00 mwh/h cet min15 sa"),
    ("Solar act DE",      "pro de spv ec00 mwh/h cet min15 a"),
    ("Wind act DE",       "pro de wnd ec00 mwh/h cet min15 a"),
    ("Consumption act DE","con de ec00 mwh/h cet min15 a"),
    ("Solar normal DE",   "pro de spv mwh/h cet min15 n"),
    ("Wind normal DE",    "pro de wnd mwh/h cet min15 n"),
    ("Installed PV DE",   "cap de spv mw cet min15 a"),
    ("Nuclear act DE",    "pro de nuc mwh/h cet min15 a"),
    # real names resolved via search() — §B names were examples (plan rule)
    ("Gas TTF",           "gas pri nl ttf fut front-month clo spectron €/mwh cet d a"),
    ("Solar FCST DE",     "pro de spv ec00 mwh/h cet min15 f"),
    ("Wind FCST DE",      "pro de wnd ec00 mwh/h cet min15 f"),
    ("Residual FCST DE",  "rdl de ec00 mwh/h cet min15 f"),
    ("Consumption FCST DE","con de ec00 mwh/h cet min15 f"),
    ("CO2 EUA",           "co2 pri ets eua €/eua cet m f"),
]

rows: list[dict] = []


def resolve(session, name: str):
    try:
        hits = session.search(name=name) or []
    except Exception:
        hits = []
    if not hits:
        # broaden: replace spaces with wildcard-friendly search on key tokens
        try:
            hits = session.search(name=name.replace("ec00 ", "")) or []
        except Exception:
            hits = []
    if not hits:
        try:
            c = session.get_curve(name=name)
            return c, "get_curve"
        except Exception:
            return None, "not found"
    for h in hits:
        if getattr(h, "name", None) == name:
            return h, f"search({len(hits)})"
    return hits[0], f"search({len(hits)}, fuzzy)"


def span(s: pd.Series) -> str:
    s = s.dropna()
    if len(s) == 0:
        return "0 rows"
    return f"{len(s)} pts {s.index.min():%Y-%m-%d}..{s.index.max():%Y-%m-%d} " \
           f"min={s.min():.2f} max={s.max():.2f}"


def probe_ts(curve) -> str:
    try:
        ts = curve.get_data(data_from=DEMO_DAY, data_to="2026-05-20",
                            function="AVERAGE", frequency="D")
        return "TS(daily): " + span(ts.to_pandas())
    except Exception as e:
        try:
            ts = curve.get_data(data_from=DEMO_DAY, data_to="2026-02-01")
            return "TS(raw): " + span(ts.to_pandas())
        except Exception as e2:
            return f"TS read FAILED: {type(e2).__name__}: {str(e2)[:90]}"


def probe_instances(curve) -> str:
    # Discover the REAL issue_dates first, then read them (UC2 mechanism).
    try:
        meta = curve.search_instances(issue_date_from=DEMO_DAY,
                                      issue_date_to="2026-01-15")
        iss = sorted(m.issue_date for m in meta)
        if not iss:
            meta = curve.search_instances(issue_date_from=DEMO_DAY,
                                          issue_date_to="2026-06-01")
            iss = sorted(m.issue_date for m in meta)
    except Exception as e:
        return f"INSTANCES search_instances FAILED: {type(e).__name__}: {e}"
    if not iss:
        return "INSTANCES [no issue_dates in 2026 window]"
    got = []
    for idt in iss[:3]:
        try:
            inst = curve.get_instance(issue_date=idt, data_from=DEMO_DAY,
                                      data_to="2026-12-31")
            n = len(inst.to_pandas().dropna()) if inst is not None else 0
            got.append((str(idt)[:16], n))
        except Exception as e:
            got.append((str(idt)[:16], f"ERR({type(e).__name__})"))
    nwith = sum(1 for _, n in got if isinstance(n, int) and n > 0)
    flag = "REVISION-OK" if nwith >= 2 else f"only {nwith} issue(s) w/ data"
    body = " ".join(f"{d}={n}" for d, n in got)
    return f"INSTANCES [{flag}] {len(iss)} issue_dates; {body}"


def run_volue():
    import volue_insight_timeseries as vit

    session = vit.Session(
        urlbase=os.environ.get("VOLUE_INSIGHT_API_URL"),
        auth_urlbase=os.environ.get("VOLUE_INSIGHT_AUTH_URL"),
        client_id=os.environ["VOLUE_INSIGHT_CLIENT_ID"],
        client_secret=os.environ["VOLUE_INSIGHT_CLIENT_SECRET"],
        timeout=300,
    )
    for label, name in CURVES:
        curve, how = resolve(session, name)
        if curve is None:
            rows.append({"label": label, "ok": False,
                         "detail": f"NOT FOUND ({name!r})"})
            print(f"  [--] {label:22s} NOT FOUND", flush=True)
            continue
        ctype = str(getattr(curve, "curve_type", "?"))
        rname = getattr(curve, "name", name)
        if "INSTANCE" in ctype.upper():
            detail = probe_instances(curve)
            ok = "REVISION-OK" in detail
        else:
            detail = probe_ts(curve)
            ok = not any(m in detail for m in
                         ("FAILED", "0 rows", "0 pts 0", " 0 pts"))
        rows.append({"label": label, "ok": ok,
                     "detail": f"{ctype} via {how} | {detail}",
                     "rname": rname})
        print(f"  [{'OK' if ok else 'XX'}] {label:22s} {ctype:18s} {detail}",
              flush=True)
    # Temp backcast: names vary hardest -> search-only existence check.
    try:
        h = session.search(name="tt de * test °c cet h s") or \
            session.search(commodity="tt", area="de") or []
        msg = f"{len(h)} match(es)" + (f" e.g. {h[0].name!r}" if h else "")
        rows.append({"label": "Temp backcast", "ok": len(h) > 0,
                     "detail": f"search-only: {msg}"})
        print(f"  [{'OK' if h else '--'}] {'Temp backcast':22s} search-only: {msg}",
              flush=True)
    except Exception as e:
        print(f"  [--] Temp backcast search ERR {type(e).__name__}: {e}",
              flush=True)


def run_optimeering():
    print("\n--- Optimeering real retrieve() ---", flush=True)
    from optimeering_beta import Configuration, OptimeeringClient

    c = OptimeeringClient(Configuration(
        host=os.environ.get("OPTIMEERING_HOST"),
        api_key=os.environ["OPTIMEERING_API_KEY"]))
    pa = c.predictions_api
    for area in (["NO1"], ["DE"]):
        try:
            ser = pa.list_series(area=area, product=["Imbalance"],
                                 statistic=["Point"])
            items = getattr(ser, "items", []) or []
            if not items:
                print(f"  [--] {area[0]} Imbalance/Point: 0 series", flush=True)
                rows.append({"label": f"Opti {area[0]} Imb",
                             "ok": False, "detail": "0 series"})
                continue
            sid = items[0].id
            data = pa.retrieve(series_id=[sid], start="-P14D")
            try:
                df = data.to_pandas(unpack_value_method="new_columns")
                n = len(df)
            except Exception:
                n = len(getattr(data, "items", []) or [])
            ok = n > 0
            print(f"  [{'OK' if ok else 'XX'}] {area[0]} Imbalance/Point "
                  f"series_id={sid} retrieve(-P14D) -> {n} rows", flush=True)
            rows.append({"label": f"Opti {area[0]} Imb",
                         "ok": ok, "detail": f"sid={sid} rows={n}"})
        except Exception as e:
            print(f"  [XX] {area[0]} retrieve ERR {type(e).__name__}: "
                  f"{str(e)[:120]}", flush=True)
            rows.append({"label": f"Opti {area[0]} Imb",
                         "ok": False, "detail": f"{type(e).__name__}"})


if __name__ == "__main__":
    print("=== Volta coverage probe (VOLUE_DATA §B/§C) ===", flush=True)
    print("--- Volue curves (search-first, runtime-typed) ---", flush=True)
    run_volue()
    run_optimeering()
    ok = [r for r in rows if r["ok"]]
    expected = [r for r in rows if not r["ok"] and r["label"] in EXPECTED_EMPTY]
    bad = [r for r in rows if not r["ok"] and r["label"] not in EXPECTED_EMPTY]
    print(f"\n=== SUMMARY: {len(ok)}/{len(rows)} OK, "
          f"{len(expected)} expected-empty (per plan), "
          f"{len(bad)} real failures ===", flush=True)
    if expected:
        print("EXPECTED-EMPTY (documented in VOLUE_DATA §E, not defects):",
              flush=True)
        for r in expected:
            print(f"  - {r['label']}: {r['detail']}", flush=True)
    if bad:
        print("REAL FAILURES:", flush=True)
        for r in bad:
            print(f"  - {r['label']}: {r['detail']}", flush=True)
    sys.exit(0 if not bad else 1)
