"""Deep operational contract for Optimeering — param vocab, the filter/retrieve
patterns, the prediction data model, statistic types, versioned/simulated
(Nordic backtest). Read-only, 0 €.
Run: .venv/bin/python scripts/probe_optimeering_deep.py
"""
from __future__ import annotations

import os
import traceback

from dotenv import load_dotenv

load_dotenv(".env.local")
from optimeering_beta import Configuration, OptimeeringClient

C = OptimeeringClient(Configuration(host=os.environ.get("OPTIMEERING_HOST"),
                                    api_key=os.environ["OPTIMEERING_API_KEY"]))
PA = C.predictions_api


def hdr(t):
    print(f"\n{'='*4} {t} {'='*4}", flush=True)


def sect(fn):
    try:
        fn()
    except Exception:
        traceback.print_exc()


def vocab():
    hdr("1. Parameter vocabulary (valid filter values)")
    for p in ("area", "product", "statistic", "resolution", "unit_type"):
        try:
            v = PA.list_parameters(param=p)
            v = list(v) if hasattr(v, "__iter__") else v
            print(f"  param={p!r}: {len(v) if hasattr(v,'__len__') else '?'}"
                  f" -> {str(v)[:160]}")
        except Exception as e:
            print(f"  param={p!r}: ERR {type(e).__name__}: {str(e)[:120]}")
    # derive vocab from the series catalogue as ground truth
    ser = PA.list_series()
    its = ser.items
    for dim in ("product", "statistic", "area", "resolution"):
        vals = sorted({getattr(s, dim, None) for s in its} - {None})
        print(f"  series.{dim}: {len(vals)} -> {vals[:14]}")


def series_obj():
    hdr("2. list_series object + filter/retrieve pattern (§A.5)")
    ser = PA.list_series(area=["NO1"], product=["Imbalance"],
                         statistic=["Point"])
    print(f"  type={type(ser).__name__} attrs="
          f"{[a for a in dir(ser) if not a.startswith('_')][:14]}")
    it = ser.items[0]
    print(f"  series item attrs: "
          f"{[a for a in dir(it) if not a.startswith('_')][:14]}")
    print(f"  sample: id={it.id} area={it.area} product={it.product} "
          f"stat={it.statistic} res={getattr(it,'resolution','?')} "
          f"unit={getattr(it,'unit_type','?')}")
    if hasattr(ser, "filter") and hasattr(ser, "retrieve"):
        fs = ser.filter(product=["Imbalance"], statistic=["Point"])
        data = fs.retrieve(start="-P7D")
        print(f"  ser.filter().retrieve('-P7D') OK -> {type(data).__name__}")
    else:
        print("  (no .filter/.retrieve on list obj; use PA.retrieve)")


def data_model():
    hdr("3. retrieve() data model + to_pandas shapes")
    ser = PA.list_series(area=["NO1"], product=["Imbalance"],
                         statistic=["Point"])
    sid = ser.items[0].id
    data = PA.retrieve(series_id=[sid], start="-P3D")
    di = data.items[0] if getattr(data, "items", None) else None
    if di is not None:
        print(f"  data item attrs: "
              f"{[a for a in dir(di) if not a.startswith('_')][:16]}")
    for m in ("new_columns", "explode", "single_column"):
        try:
            df = data.to_pandas(unpack_value_method=m)
            print(f"  to_pandas({m}): {df.shape} cols={list(df.columns)[:8]}")
            print(f"    dtypes={dict(list(df.dtypes.astype(str).items())[:6])}")
            print(f"    head1={df.head(1).to_dict('records')}")
            break
        except Exception as e:
            print(f"  to_pandas({m}): ERR {type(e).__name__}: {str(e)[:90]}")


def statistics():
    hdr("4. Statistic types -> statistic-specific value columns")
    # Use active NO1 series (the full catalogue's first-per-stat hits
    # inactive mFRR series). value_* columns differ per statistic.
    cat = PA.list_series(area=["NO1"])
    by = {}
    for s in cat.items:
        by.setdefault(s.statistic, s)
    for st, s in by.items():
        try:
            d = PA.retrieve(series_id=[s.id], start="-P10D")
            df = d.to_pandas(unpack_value_method="new_columns")
            vc = [c for c in df.columns if c.startswith("value")]
            note = "" if len(df) else " (this series inactive; mechanism " \
                "proven on other stats)"
            print(f"  {st:18s} sid={s.id} {s.product}: rows={len(df)} "
                  f"value_cols={vc}{note}")
        except Exception as e:
            print(f"  {st}: ERR {type(e).__name__}: {str(e)[:90]}")


def versioned():
    hdr("5. retrieve_versioned (Nordic backtest path, §A.5)")
    # BOUNDED: filter to ONE version + short window. retrieve_versioned over
    # the whole version list + long window pulls millions of rows / hangs.
    vl = PA.list_version(area=["NO1"], product=["Imbalance"],
                         statistic=["Point"])
    vers = sorted({getattr(v, "version", None) for v in vl.items} - {None})
    print(f"  versions: {vers}  (1.2.1 = the plan's §A.5 example version)")
    sub = vl.filter(version=[vers[-1]]) if hasattr(vl, "filter") else vl
    try:
        dv = PA.retrieve_versioned(versioned_series=sub,
                                   include_simulated=True, start="-P5D")
        df = dv.to_pandas(unpack_value_method="new_columns")
        vc = (df["is_simulated"].value_counts().to_dict()
              if "is_simulated" in df else {})
        print(f"  retrieve_versioned(v={vers[-1]}, -P5D, "
              f"include_simulated=True): rows={len(df)} is_simulated={vc}")
        print("  NOTE: is_simulated=True not surfaced in quick windows; "
              "Nordic backtest depth is a deeper exploration — path itself works.")
    except Exception as e:
        print(f"  retrieve_versioned: ERR {type(e).__name__}: {str(e)[:140]}")


if __name__ == "__main__":
    print("=== Optimeering — deep operational contract ===", flush=True)
    for f in (vocab, series_obj, data_model, statistics, versioned):
        sect(f)
    print("\n=== done ===", flush=True)
