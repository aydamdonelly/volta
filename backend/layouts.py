"""LAYOUTS — 3 pre-baked thesis bundles. Counter-evidence + intent_recommendation mandatory."""
from __future__ import annotations
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger("volta.layouts")

THESIS_KEYS = ("de_duck_curve", "de_price_crash", "dk1_se4_spread", "ad_hoc")


@dataclass
class WindowSpec:
    window_type: str
    title: str
    summary_line: str
    curve_keys: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


@dataclass
class LayoutBundle:
    thesis_key: str
    theme_label: str
    intent_recommendation: str
    windows: list[WindowSpec]


LAYOUTS: dict[str, LayoutBundle] = {
    "de_duck_curve": LayoutBundle(
        thesis_key="de_duck_curve",
        theme_label="DE Spot — Solar Duck-Curve",
        intent_recommendation=(
            "Based on the solar duck-curve thesis, here's the canvas: "
            "day-ahead price, solar generation, residual demand, and forecast context."
        ),
        windows=[
            WindowSpec("chart", "DE Day-Ahead Price + Solar",
                       "Intraday spot overlaid with solar generation.",
                       ["pri_de_spot_h", "pro_de_spv_act"],
                       extra={"chart_type": "line", "y_unit": "€/MWh"}),
            WindowSpec("text", "Why solar dominates the duck",
                       "Midday solar peak depresses spot prices; demand stays flat.",
                       [], extra={"narration_placeholder": True}),
            WindowSpec("counter", "Counter-Evidence",
                       "CO2 EUA + wind forecast push back on a one-sided solar narrative.",
                       ["co2_pri_eua", "pro_de_wnd_ec00_f"],
                       extra={"badge": "counter_evidence", "claims": [
                           {"claim": "CO2 EUA front-month", "unit": "€/EUA",
                            "source_curve": "co2 pri ets eua €/eua cet m f"},
                           {"claim": "Wind forecast (ec00) revision", "unit": "MWh/h",
                            "source_curve": "pro de wnd ec00 mwh/h cet min15 f"},
                       ]}),
            WindowSpec("news", "Derived News (DE)",
                       "Context-only events tied to today's data deltas.",
                       [], extra={"area": "DE", "badge": "context_not_proof"}),
        ],
    ),
    "de_price_crash": LayoutBundle(
        thesis_key="de_price_crash",
        theme_label="DE Spot — March 6 Day View",
        intent_recommendation=(
            "Based on the spot price thesis, here's the canvas: "
            "March-6 spot price, consumption, wind/solar, and gas/CO2 context."
        ),
        windows=[
            WindowSpec("chart", "DE Spot · Wind · Consumption — March 6",
                       "Spot price overlaid with wind generation and consumption.",
                       ["pri_de_spot_h", "pro_de_wnd_act", "con_de_act"],
                       extra={"chart_type": "line", "y_unit": "€/MWh and MWh/h",
                              "dual_axis": True}),
            WindowSpec("text", "What's driving the price",
                       "Low wind output + winter consumption peak + thermal floor (gas TTF).",
                       [], extra={"narration_placeholder": True}),
            WindowSpec("counter", "Counter-Evidence",
                       "Consumption trend and cross-border context.",
                       ["con_de_act", "pri_nl_spot_h", "pri_be_spot_h"],
                       extra={"badge": "counter_evidence", "claims": [
                           {"claim": "DE consumption (Mar-6 daily avg)", "unit": "MWh/h",
                            "source_curve": "con de mwh/h cet min15 a"},
                           {"claim": "NL spot price (Mar-6 daily avg)", "unit": "€/MWh",
                            "source_curve": "pri nl spot €/mwh cet h a"},
                           {"claim": "BE spot price (Mar-6 daily avg)", "unit": "€/MWh",
                            "source_curve": "pri be spot €/mwh cet h a"},
                       ]}),
            WindowSpec("news", "Derived News (DE)",
                       "Forecast revisions and price spikes flagged on Mar-6.",
                       [], extra={"area": "DE", "badge": "context_not_proof"}),
        ],
    ),
    "dk1_se4_spread": LayoutBundle(
        thesis_key="dk1_se4_spread",
        theme_label="DK1 ↔ SE4 Spread + Nordic Imbalance",
        intent_recommendation=(
            "Based on the Nordic cross-border thesis, here's the canvas: "
            "DK1↔SE4 spot spread, NO1/DK1/SE4 imbalance band, and Volue context."
        ),
        windows=[
            WindowSpec("chart", "DK1 vs SE4 Day-Ahead",
                       "Hourly spot prices side-by-side.",
                       ["pri_dk1_spot_h", "pri_se4_spot_h"],
                       extra={"chart_type": "line", "y_unit": "€/MWh"}),
            WindowSpec("text", "Spread drivers",
                       "Wind, transmission constraints, and imbalance signals.",
                       [], extra={"narration_placeholder": True}),
            WindowSpec("counter", "Counter-Evidence — Optimeering Imbalance Band",
                       "NO1/DK1/SE4 imbalance quantile predictions (P10–P90 band).",
                       ["optimeering_no1_imbalance_point",
                        "optimeering_dk1_imbalance_point",
                        "optimeering_se4_imbalance_point"],
                       extra={"badge": "counter_evidence", "claims": [
                           {"claim": "NO1 Imbalance Point", "unit": "MWh",
                            "source_curve": "optimeering NO1 Imbalance Point"},
                           {"claim": "DK1 Imbalance Point", "unit": "MWh",
                            "source_curve": "optimeering DK1 Imbalance Point"},
                           {"claim": "SE4 Imbalance Point", "unit": "MWh",
                            "source_curve": "optimeering SE4 Imbalance Point"},
                       ]}),
            WindowSpec("news", "Derived News (Nordic)",
                       "Imbalance quantile-range spikes (Rule C).",
                       [], extra={"area": "DK1", "badge": "context_not_proof"}),
        ],
    ),
    "ad_hoc": LayoutBundle(
        thesis_key="ad_hoc",
        theme_label="Ad-hoc — DE Context Canvas",
        intent_recommendation=(
            "No baked thesis matched — here's a general DE context canvas: "
            "spot price, cross-border context, CO2/gas signals, and Sonnet narration "
            "synthesized for your question."
        ),
        windows=[
            WindowSpec("chart", "DE Spot — Today",
                       "Hourly day-ahead spot price (default DE view).",
                       ["pri_de_spot_h"],
                       extra={"chart_type": "line", "y_unit": "€/MWh"}),
            WindowSpec("text", "Volta synthesis",
                       "Sonnet writes a tailored answer to your free-form question.",
                       [], extra={"narration_placeholder": True}),
            WindowSpec("counter", "Counter-Evidence — DE Cross-Border",
                       "NL/BE spot prices + CO2 EUA front-month for sanity context.",
                       ["pri_nl_spot_h", "pri_be_spot_h", "co2_pri_eua"],
                       extra={"badge": "counter_evidence", "claims": [
                           {"claim": "NL spot price (daily avg)", "unit": "€/MWh",
                            "source_curve": "pri nl spot €/mwh cet h a"},
                           {"claim": "BE spot price (daily avg)", "unit": "€/MWh",
                            "source_curve": "pri be spot €/mwh cet h a"},
                           {"claim": "CO2 EUA front-month", "unit": "€/EUA",
                            "source_curve": "co2 pri ets eua €/eua cet m f"},
                       ]}),
            WindowSpec("news", "Derived News (DE)",
                       "Events tied to today's data deltas (context, not proof).",
                       [], extra={"area": "DE", "badge": "context_not_proof"}),
        ],
    ),
}


def get_intent_recommendation(thesis_key: str) -> str:
    return LAYOUTS[thesis_key].intent_recommendation


def list_thesis_keys() -> tuple[str, ...]:
    return THESIS_KEYS


def all_curve_keys() -> set[str]:
    keys: set[str] = set()
    for b in LAYOUTS.values():
        for w in b.windows:
            keys.update(w.curve_keys)
    return keys


def _hydrate_counter_points(points: list[dict], clock) -> list[dict]:
    """Fill `value` + `ts` on counter-evidence claims from cache.

    Live mode: window is the 24h ending at clock.now(). Offline mode: DEFAULT_DEMO_DAY.
    Best-effort: a missing curve / empty parquet is swallowed and the claim is
    returned unchanged.
    """
    import os

    import pandas as pd
    from backend.cache import get_meta, read_optimeering, read_ts
    from backend.clock import DEFAULT_DEMO_DAY

    if os.environ.get("LIVE_VOLUE", "1") == "1":
        now = pd.Timestamp(clock.now()).tz_convert("UTC") if pd.Timestamp(clock.now()).tz is not None else pd.Timestamp(clock.now()).tz_localize("UTC")
        day_end = now
        day_start = now - pd.Timedelta(hours=24)
    else:
        day_start = pd.Timestamp(DEFAULT_DEMO_DAY).tz_localize("UTC")
        day_end = day_start + pd.Timedelta(hours=23, minutes=45)
    # Backwards-compat aliases (rest of the function still references these)
    apr5_start = day_start
    apr5_end = day_end

    out: list[dict] = []
    for p in points:
        new_p = dict(p)
        sc_lower = (p.get("source_curve") or "").lower()
        candidates: list[str] = []
        if "co2" in sc_lower and "eua" in sc_lower:
            candidates = ["co2_pri_eua"]
        elif "wnd" in sc_lower and "ec00" in sc_lower:
            candidates = ["pro_de_wnd_ec00_f"]
        elif "con de" in sc_lower:
            candidates = ["con_de_act"]
        elif "pri nl spot" in sc_lower:
            candidates = ["pri_nl_spot_h"]
        elif "pri be spot" in sc_lower:
            candidates = ["pri_be_spot_h"]
        elif "optimeering" in sc_lower and "no1" in sc_lower:
            candidates = ["optimeering_no1_imbalance_point"]
        elif "optimeering" in sc_lower and "dk1" in sc_lower:
            candidates = ["optimeering_dk1_imbalance_point"]
        elif "optimeering" in sc_lower and "se4" in sc_lower:
            candidates = ["optimeering_se4_imbalance_point"]

        for key in candidates:
            try:
                meta = get_meta(key)
                if meta.get("type") == "optimeering":
                    df = read_optimeering(key, clock)
                    if not df.empty and "value_point" in df.columns:
                        sub = df[
                            (df["event_time"] >= apr5_start)
                            & (df["event_time"] <= apr5_end)
                        ]
                        if not sub.empty:
                            new_p["value"] = round(float(sub["value_point"].mean()), 2)
                            new_p["ts"] = sub["event_time"].iloc[-1].isoformat()
                else:
                    df = read_ts(key, clock)
                    if not df.empty:
                        sub = df[
                            (df["ts"] >= apr5_start)
                            & (df["ts"] <= apr5_end)
                        ]
                        if not sub.empty:
                            new_p["value"] = round(float(sub["value"].mean()), 4)
                            new_p["ts"] = sub["ts"].iloc[-1].isoformat()
            except Exception as exc:  # noqa: BLE001 — hydration is best-effort
                log.debug("hydrate skip %s: %s", key, exc)
            if new_p.get("ts"):
                break
        out.append(new_p)
    return out


def resolve(thesis_key: str, clock) -> list:
    """Hydrate LayoutBundle into 4 Window dataclasses."""
    from backend.models import Window

    if thesis_key not in LAYOUTS:
        raise KeyError(f"unknown thesis_key: {thesis_key!r}")

    bundle = LAYOUTS[thesis_key]
    now = clock.now()
    t_from = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    t_to = now.replace(hour=23, minute=45, second=0, microsecond=0).isoformat()
    theme_id = f"theme_{thesis_key}_{uuid.uuid4().hex[:8]}"

    out: list = []
    for i, ws in enumerate(bundle.windows):
        window_id = f"win_{thesis_key}_{ws.window_type}_{i}"
        if ws.window_type == "chart":
            spec = {
                "chart_type": ws.extra.get("chart_type", "line"),
                "x_key": "ts", "y_key": "value",
                "y_unit": ws.extra.get("y_unit", "€/MWh"),
                "t_from": t_from, "t_to": t_to,
                "annotations": [],
            }
        elif ws.window_type == "text":
            spec = {"body": "", "badge": None, "dismissable": True, "sources": []}
        elif ws.window_type == "news":
            spec = {"headline": "", "body": "", "badge": "context_not_proof",
                    "news_id": "", "severity": "low"}
        elif ws.window_type == "counter":
            hydrated_points = _hydrate_counter_points(ws.extra.get("claims", []), clock)
            spec = {"body": "", "badge": "counter_evidence", "dismissable": True,
                    "points": hydrated_points}
        else:
            raise RuntimeError(f"unknown window_type: {ws.window_type!r}")

        out.append(Window(
            window_id=window_id, theme_id=theme_id,
            window_type=ws.window_type,
            title=ws.title, summary_line=ws.summary_line,
            state="small", curve_keys=list(ws.curve_keys),
            spec=spec, grounding=None, raw_toggle=True,
        ))
    return out
