"""Unit tests for backend.models — dataclass round-trips + badge conventions."""
from __future__ import annotations

from backend.models import (
    Annotation,
    CanvasSnapshot,
    CanvasState,
    ChartSpec,
    Claim,
    CounterSpec,
    DerivedNewsEvent,
    FundamentalBreakdown,
    NewsSpec,
    SourcedValue,
    TextSpec,
    Window,
    WsFrame,
    from_dict,
    to_dict,
)


def test_sourced_value_roundtrip() -> None:
    sv = SourcedValue(
        label="DE day-ahead min",
        value=-499.0,
        unit="€/MWh",
        source_curve="pri de spot €/mwh cet h a",
        ts="2026-04-05T12:00:00Z",
    )
    d = to_dict(sv)
    assert d == {
        "label": "DE day-ahead min",
        "value": -499.0,
        "unit": "€/MWh",
        "source_curve": "pri de spot €/mwh cet h a",
        "ts": "2026-04-05T12:00:00Z",
    }
    sv2 = from_dict(SourcedValue, d)
    assert sv2 == sv


def test_window_with_chart_spec_serializes_annotations() -> None:
    spec = ChartSpec(
        chart_type="line",
        x_key="ts",
        y_key="value",
        y_unit="€/MWh",
        t_from="2026-04-05T00:00:00Z",
        t_to="2026-04-06T00:00:00Z",
        annotations=[
            Annotation(ts="2026-04-05T13:00:00Z", label="Min -€16,34", color="#000"),
            Annotation(ts="2026-04-05T18:00:00Z", label="Recovery"),
        ],
    )
    win = Window(
        window_id="w_price",
        theme_id="de_price_crash_001",
        window_type="chart",
        title="DE Day-Ahead Price",
        summary_line="Daily mean -€16,34/MWh",
        state="small",
        curve_keys=["pri_de_spot_eur_mwh_cet_h_a"],
        spec=to_dict(spec),
        grounding=SourcedValue(
            label="Daily mean",
            value=-16.34,
            unit="€/MWh",
            source_curve="pri de spot €/mwh cet h a",
            ts="2026-04-05T00:00:00Z",
        ),
        raw_toggle=True,
    )
    d = to_dict(win)
    assert d["spec"]["annotations"][0]["label"] == "Min -€16,34"
    assert d["spec"]["annotations"][1]["color"] is None
    assert d["grounding"]["value"] == -16.34
    assert d["state"] == "small"
    assert d["raw_toggle"] is True


def test_fundamental_breakdown_residual_flag_preserved() -> None:
    drivers = [
        SourcedValue("consumption", 52000.0, "MWh", "con de mwh/h cet min15 a", "2026-04-05T12:00:00Z"),
        SourcedValue("solar", 18000.0, "MWh", "pro de spv mwh/h cet min15 a", "2026-04-05T12:00:00Z"),
        SourcedValue("wind", 6000.0, "MWh", "pro de wnd mwh/h cet min15 a", "2026-04-05T12:00:00Z"),
        SourcedValue("residual", 28000.0, "MWh", "rdl de mwh/h cet min15 sa", "2026-04-05T12:00:00Z"),
    ]
    bd = FundamentalBreakdown(
        area="DE",
        focus="price_crash",
        headline="DE day-ahead fell to -€16,34/MWh on 2026-04-05",
        drivers=drivers,
        method_note="residual = consumption − solar − wind (deterministic)",
        residual_check_ok=True,
        t_from="2026-04-05T00:00:00Z",
        t_to="2026-04-06T00:00:00Z",
    )
    d = to_dict(bd)
    assert d["residual_check_ok"] is True
    assert d["drivers"][3]["label"] == "residual"
    bd2 = from_dict(FundamentalBreakdown, d)
    assert bd2.residual_check_ok is True
    assert bd2.drivers[0].source_curve == "con de mwh/h cet min15 a"
    assert bd2.drivers[0].value == 52000.0


def test_derived_news_event_hedged_default() -> None:
    """All emitted DerivedNewsEvents must carry hedged=True + hedged_text."""
    ev = DerivedNewsEvent(
        news_id="spike_de_2026-04-05_1300",
        area="DE",
        severity="high",
        headline="DE-Preis auf -€499/MWh gefallen",
        delta_value=-499.0,
        unit="€/MWh",
        source_curve="pri de spot €/mwh cet h a",
        ts="2026-04-05T13:00:00Z",
        hedged=True,
        hedged_text="This could be related to weather/holiday — not a proven cause.",
    )
    d = to_dict(ev)
    assert d["hedged"] is True
    assert "could" in d["hedged_text"] or "context" in d["hedged_text"].lower()


def test_ws_frame_envelope() -> None:
    frame = WsFrame(
        op="spawn_theme",
        seq=1,
        ts="2026-04-05T00:00:00Z",
        payload={"theme_id": "de_price_crash_001", "label": "DE Price Crash"},
    )
    d = to_dict(frame)
    assert d == {
        "op": "spawn_theme",
        "seq": 1,
        "ts": "2026-04-05T00:00:00Z",
        "payload": {"theme_id": "de_price_crash_001", "label": "DE Price Crash"},
    }


def test_canvas_snapshot_roundtrip() -> None:
    snap = CanvasSnapshot(
        windows=[{"window_id": "w1", "window_type": "chart"}],
        themes=["de_price_crash_001"],
        virtual_now="2026-04-05T14:00:00Z",
    )
    d = to_dict(snap)
    assert d["virtual_now"] == "2026-04-05T14:00:00Z"
    assert d["themes"] == ["de_price_crash_001"]
    snap2 = from_dict(CanvasSnapshot, d)
    assert snap2 == snap

    # CanvasState round-trip
    state = CanvasState(themes=[{"theme_id": "t1", "windows": []}])
    d2 = to_dict(state)
    assert d2 == {"themes": [{"theme_id": "t1", "windows": []}]}
    state2 = from_dict(CanvasState, d2)
    assert state2 == state


def test_news_spec_badge_is_context_not_proof() -> None:
    """Convention: NewsSpec.badge SHOULD be "context_not_proof"; explicit pass-through."""
    spec = NewsSpec(
        headline="DE-Preis crash",
        body="Daily mean -€16,34/MWh on 2026-04-05",
        badge="context_not_proof",
        news_id="spike_de_2026-04-05",
        severity="high",
    )
    d = to_dict(spec)
    assert d["badge"] == "context_not_proof"

    # Other badges allowed but flagged via convention only.
    other = NewsSpec(
        headline="x",
        body="y",
        badge="other",
        news_id="n",
        severity="low",
    )
    assert to_dict(other)["badge"] == "other"


def test_counter_spec_badge_is_counter_evidence() -> None:
    """Convention: CounterSpec.badge MUST be 'counter_evidence'; claims preserved."""
    spec = CounterSpec(
        body="Counter points:",
        badge="counter_evidence",
        dismissable=True,
        points=[
            Claim(
                claim="CO2 EUA price unchanged",
                value=85.2,
                unit="€/EUA",
                source_curve="co2 pri ets eua €/eua cet m f",
                ts="2026-04-05T00:00:00Z",
            )
        ],
    )
    d = to_dict(spec)
    assert d["badge"] == "counter_evidence"
    assert d["points"][0]["claim"] == "CO2 EUA price unchanged"
    assert d["points"][0]["value"] == 85.2

    # Round-trip uses to_dict + manual reconstruction since CounterSpec has nested Claims.
    # ChartSpec / TextSpec / CounterSpec primarily serialize one way; ensure asdict works.
    text = TextSpec(body="hello", badge=None, dismissable=False, sources=[])
    assert to_dict(text)["badge"] is None
