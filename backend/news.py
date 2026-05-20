"""DerivedNewsEngine — Rule A (forecast revision), Rule B (price spike), Rule C (optimeering range).

Every DerivedNewsEvent has hedged=True and hedged_text containing "context" or "could be".

Rules:
- Rule A — Forecast Revision: compare latest issue_date vs previous for `pro de spv ec00 f`
  and `pro de wnd ec00 f`. Fire when max|Δ| over common ts >= threshold.
- Rule B — Price Spike: read `pri_de_spot_min15` (fallback `pri_de_spot_h`); fire when
  |Δprice| between last two samples >= threshold OR last < 0 (hard negative trigger).
- Rule C — Optimeering Quantile Range: Q90 - Q10 spread > threshold.

Cooldown: 30min per news_id. Empty cache → returns [] (graceful).
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_THRESHOLDS = {
    # Tuned against March-1..March-8 cached data. Rule A compares the latest
    # *visible* issue_date to the previous one (virtual-now masked) — so a new
    # issue crossing the cursor fires the toast once per 30-min cooldown.
    # - solar (spv) visible-pair max delta range: 1865..7951 MWh → 1500 fires
    #   on every real revision in the demo window.
    # - wind (wnd) visible-pair max delta range: 1403..6616 MWh → 1200 fires
    #   on every revision (smallest is 1403 between 03-06 and 03-07).
    # - price spike: 25 EUR is roughly p85 of consecutive-hour |Δ| on
    #   pri_de_spot_h (median 9 EUR, p90 36 EUR).
    # - optimeering Q90-Q10 spread: 500 MWh trips only on the genuine outlier
    #   (per-row max ~568 MWh, p95 ~40 MWh) — intentionally rare.
    "spv_forecast_delta_mwh": 1500.0,
    "wnd_forecast_delta_mwh": 1200.0,
    "price_spike_eur_15min": 25.0,
    "optimeering_quantile_range_mwh": 500.0,
}
COOLDOWN_MIN = 30
HEDGE_PHRASES = {
    "rule_a": "Forecast revision detected — context, not proof; could reflect a changed weather model.",
    "rule_b": "Price movement detected — context, not proof; could reflect short-term sentiment.",
    "rule_c": "Optimeering quantile spread widened — context, not proof; could reflect uncertainty.",
}

log = logging.getLogger("volta.news")


class DerivedNewsEngine:
    """Stateful engine fired once per virtual-now tick.

    Holds 30-min cooldown per ``news_id``. ``events_at(t)`` is the only public
    entrypoint besides ``reset_cooldowns()``.
    """

    def __init__(self, clock, thresholds: dict | None = None) -> None:
        self._clock = clock
        self._thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self._cooldown: dict[str, datetime] = {}
        # Edge-trigger memory.
        # - last_iss_by_src: latest issue_date observed per forecast curve;
        #   Rule A fires only when a *new* issue crosses virtual_now.
        # - last_price_ts_by_src: latest spot-price ts observed per curve;
        #   Rule B fires only when a *new* hourly sample crosses virtual_now.
        self._last_iss_by_src: dict[str, Any] = {}
        self._last_price_ts_by_src: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def events_at(self, t: datetime) -> list:
        if t.tzinfo is None:
            raise ValueError("t must be tz-aware")

        events: list = []
        events.extend(self._rule_a_forecast_revision(t))
        events.extend(self._rule_b_price_spike(t))
        events.extend(self._rule_c_optimeering_range(t))

        kept: list = []
        for ev in events:
            assert ev.hedged is True, f"event {ev.news_id} hedged=False"
            assert any(
                p in ev.hedged_text.lower() for p in ("context", "could")
            ), f"hedged_text missing required phrase: {ev.hedged_text!r}"
            last = self._cooldown.get(ev.news_id)
            if last is None or (t - last) >= timedelta(minutes=COOLDOWN_MIN):
                self._cooldown[ev.news_id] = t
                kept.append(ev)
        return kept

    def reset_cooldowns(self) -> None:
        self._cooldown.clear()
        self._last_iss_by_src.clear()
        self._last_price_ts_by_src.clear()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _severity_for(self, abs_delta: float, threshold: float) -> str:
        if abs_delta >= 2.0 * threshold:
            return "high"
        if abs_delta >= 1.5 * threshold:
            return "med"
        return "low"

    def _rule_a_forecast_revision(self, t: datetime) -> list:
        """Compare latest vs previous issue_date for ec00 forecast curves."""
        from backend.models import DerivedNewsEvent
        from backend import cache as cache_mod

        out: list = []
        rules = [
            ("pro_de_spv_ec00_f", "DE solar forecast",
             "pro de spv ec00 mwh/h cet min15 f", "spv_forecast_delta_mwh"),
            ("pro_de_wnd_ec00_f", "DE wind forecast",
             "pro de wnd ec00 mwh/h cet min15 f", "wnd_forecast_delta_mwh"),
        ]

        for src_key, label, source_curve, threshold_key in rules:
            try:
                latest = cache_mod.read_latest_instance(src_key, self._clock)
                if latest is None or getattr(latest, "empty", True):
                    continue
                if "issue_date" not in latest.columns or "value" not in latest.columns:
                    continue

                full = cache_mod.get_instance_history(src_key, self._clock)
                if full is None or getattr(full, "empty", True):
                    continue

                # Respect virtual_now: only consider issue_dates already
                # released by the current cursor. Without this filter, the
                # rule leaks future revisions into the replay.
                iss_all = sorted(full["issue_date"].unique())
                iss_unique = [d for d in iss_all if d <= t]
                if len(iss_unique) < 2:
                    continue

                latest_iss = iss_unique[-1]
                prev_iss = iss_unique[-2]

                # Edge-trigger: only fire when the latest visible issue_date
                # is *new* compared with the last observation. Prevents the
                # rule from drumming the same revision once per cooldown.
                last_seen = self._last_iss_by_src.get(src_key)
                if last_seen is not None and last_seen == latest_iss:
                    continue
                self._last_iss_by_src[src_key] = latest_iss

                latest_rows = full[full["issue_date"] == latest_iss]
                prev_rows = full[full["issue_date"] == prev_iss]
                if latest_rows.empty or prev_rows.empty:
                    continue

                merged = latest_rows[["ts", "value"]].merge(
                    prev_rows[["ts", "value"]],
                    on="ts",
                    suffixes=("_latest", "_prev"),
                )
                if merged.empty:
                    continue

                delta = float((merged["value_latest"] - merged["value_prev"]).abs().max())
                threshold = self._thresholds[threshold_key]
                if delta < threshold:
                    continue

                severity = self._severity_for(delta, threshold)
                news_id = f"forecast_revision_{src_key}"
                out.append(DerivedNewsEvent(
                    news_id=news_id,
                    area="DE",
                    severity=severity,
                    headline=f"{label} revised — max |Δ|={delta:.0f} MWh",
                    delta_value=delta,
                    unit="MWh",
                    source_curve=source_curve,
                    ts=t.isoformat(),
                    hedged=True,
                    hedged_text=HEDGE_PHRASES["rule_a"],
                ))
            except Exception as e:
                log.debug("rule_a %s: %s", src_key, e)
        return out

    def _rule_b_price_spike(self, t: datetime) -> list:
        """Detect |Δprice| spike across latest two samples or negative price."""
        from backend.models import DerivedNewsEvent
        from backend import cache as cache_mod

        out: list = []
        threshold = self._thresholds["price_spike_eur_15min"]

        chosen_key: str | None = None
        for candidate in ("pri_de_spot_min15", "pri_de_spot_h"):
            try:
                cache_mod.get_meta(candidate)
                chosen_key = candidate
                break
            except Exception:
                continue

        if chosen_key is None:
            return out

        try:
            ts_df = cache_mod.read_ts(chosen_key, self._clock)
            if ts_df is None or ts_df.empty or "value" not in ts_df.columns:
                return out
            if len(ts_df) < 2:
                return out

            sorted_df = ts_df.sort_values("ts")
            last_ts = sorted_df["ts"].iloc[-1]
            last_val = float(sorted_df["value"].iloc[-1])
            prev_val = float(sorted_df["value"].iloc[-2])
            delta = abs(last_val - prev_val)

            negative_trigger = last_val < 0
            spike_trigger = delta >= threshold
            if not (spike_trigger or negative_trigger):
                return out

            # Edge-trigger: only fire when the latest visible sample is *new*
            # for this curve. Without this the rule would emit on every tick
            # that lands inside the same hourly bar.
            last_seen_ts = self._last_price_ts_by_src.get(chosen_key)
            if last_seen_ts is not None and last_seen_ts == last_ts:
                return out
            self._last_price_ts_by_src[chosen_key] = last_ts

            severity = "high" if negative_trigger else self._severity_for(delta, threshold)
            kind = "negative" if negative_trigger else "spike"
            news_id = f"price_{kind}_{chosen_key}"
            headline = (
                f"DE spot price negative: €{last_val:.2f}/MWh (prev €{prev_val:.2f})"
                if negative_trigger
                else f"DE spot price spike: €{last_val:.2f}/MWh (Δ €{delta:.2f})"
            )
            out.append(DerivedNewsEvent(
                news_id=news_id,
                area="DE",
                severity=severity,
                headline=headline,
                delta_value=delta,
                unit="EUR/MWh",
                source_curve=chosen_key,
                ts=t.isoformat(),
                hedged=True,
                hedged_text=HEDGE_PHRASES["rule_b"],
            ))
        except Exception as e:
            log.debug("rule_b %s: %s", chosen_key, e)
        return out

    def _rule_c_optimeering_range(self, t: datetime) -> list:
        """Fire when Q90 - Q10 spread for Optimeering imbalance >= threshold."""
        from backend.models import DerivedNewsEvent
        from backend import cache as cache_mod

        out: list = []
        series_id = "optimeering_no1_imbalance_quantile"
        threshold = self._thresholds["optimeering_quantile_range_mwh"]

        try:
            cache_mod.get_meta(series_id)
        except Exception:
            return out

        try:
            df = cache_mod.read_optimeering(series_id, self._clock)
            if df is None or df.empty:
                return out

            # Quantile columns may be named various ways. We support the
            # Optimeering wide layout (value_10/value_90), an older alias
            # (value_q10/value_q90), or a tidy ("quantile" + "value") layout.
            spread = None
            if {"value_90", "value_10"}.issubset(df.columns):
                spread = float((df["value_90"] - df["value_10"]).abs().max())
            elif {"value_q90", "value_q10"}.issubset(df.columns):
                spread = float((df["value_q90"] - df["value_q10"]).abs().max())
            elif "quantile" in df.columns and "value" in df.columns:
                q90 = df[df["quantile"].isin([0.9, "0.9", 90])]
                q10 = df[df["quantile"].isin([0.1, "0.1", 10])]
                if q90.empty or q10.empty:
                    return out
                tcol = "prediction_for" if "prediction_for" in df.columns else "event_time"
                merged = q90[[tcol, "value"]].merge(
                    q10[[tcol, "value"]], on=tcol, suffixes=("_q90", "_q10")
                )
                if merged.empty:
                    return out
                spread = float((merged["value_q90"] - merged["value_q10"]).abs().max())

            if spread is None or spread < threshold:
                return out

            severity = self._severity_for(spread, threshold)
            news_id = f"optimeering_range_{series_id}"
            out.append(DerivedNewsEvent(
                news_id=news_id,
                area="NO1",
                severity=severity,
                headline=f"NO1 imbalance Q90-Q10 spread — {spread:.0f} MWh",
                delta_value=spread,
                unit="MWh",
                source_curve=series_id,
                ts=t.isoformat(),
                hedged=True,
                hedged_text=HEDGE_PHRASES["rule_c"],
            ))
        except Exception as e:
            log.debug("rule_c %s: %s", series_id, e)
        return out
