import pytest


def test_three_thesis_keys():
    """3 baked thesis keys + 'ad_hoc' catch-all = 4 total."""
    from backend.layouts import LAYOUTS, THESIS_KEYS, list_thesis_keys
    assert set(LAYOUTS.keys()) == {
        "de_duck_curve", "de_price_crash", "dk1_se4_spread", "ad_hoc"
    }
    assert THESIS_KEYS == (
        "de_duck_curve", "de_price_crash", "dk1_se4_spread", "ad_hoc"
    )
    assert list_thesis_keys() == THESIS_KEYS


def test_no_old_thesis_key():
    """Ensure de_newyear_crash was renamed."""
    from backend.layouts import LAYOUTS
    assert "de_newyear_crash" not in LAYOUTS


def test_each_layout_has_4_windows():
    from backend.layouts import LAYOUTS
    for tk, bundle in LAYOUTS.items():
        assert len(bundle.windows) == 4, f"{tk}: {len(bundle.windows)} windows"
        types = [w.window_type for w in bundle.windows]
        assert "chart" in types
        assert "text" in types
        assert "counter" in types
        assert "news" in types


def test_each_layout_has_counter_evidence_nonempty():
    from backend.layouts import LAYOUTS
    for tk, bundle in LAYOUTS.items():
        counter = next((w for w in bundle.windows if w.window_type == "counter"), None)
        assert counter is not None, f"{tk}: no counter window"
        claims = counter.extra.get("claims", [])
        assert len(claims) >= 1, f"{tk}: counter has no claims"
        for c in claims:
            assert c.get("source_curve"), f"{tk}: claim missing source_curve"


def test_each_layout_has_intent_recommendation():
    from backend.layouts import LAYOUTS, get_intent_recommendation
    for tk, bundle in LAYOUTS.items():
        assert bundle.intent_recommendation
        assert len(bundle.intent_recommendation) > 20
        assert get_intent_recommendation(tk) == bundle.intent_recommendation


def test_resolve_returns_4_windows(demo_clock):
    from backend.layouts import resolve
    windows = resolve("de_price_crash", demo_clock)
    assert len(windows) == 4
    assert {w.window_type for w in windows} == {"chart", "text", "counter", "news"}


def test_resolve_unknown_thesis_raises(demo_clock):
    from backend.layouts import resolve
    with pytest.raises(KeyError):
        resolve("nonexistent", demo_clock)


def test_dk1_se4_spread_uses_optimeering(demo_clock):
    from backend.layouts import resolve
    windows = resolve("dk1_se4_spread", demo_clock)
    counter = next(w for w in windows if w.window_type == "counter")
    assert any("optimeering" in k.lower() for k in counter.curve_keys)


def test_all_curve_keys_includes_volue_and_optimeering():
    from backend.layouts import all_curve_keys
    keys = all_curve_keys()
    assert "pri_de_spot_h" in keys
    assert any("optimeering" in k for k in keys)


def test_de_price_crash_chart_uses_spot():
    from backend.layouts import LAYOUTS
    chart = next(w for w in LAYOUTS["de_price_crash"].windows if w.window_type == "chart")
    assert "pri_de_spot_h" in chart.curve_keys


def test_no_forbidden_color_in_layouts():
    """No #ff5f00 (Volue logo orange) in any spec/extra value."""
    import json
    from backend.layouts import LAYOUTS
    blob = json.dumps([{"thesis_key": b.thesis_key, "theme_label": b.theme_label,
                        "intent_recommendation": b.intent_recommendation,
                        "windows": [{"title": w.title, "summary": w.summary_line,
                                     "extra": w.extra} for w in b.windows]}
                       for b in LAYOUTS.values()])
    assert "#ff5f00" not in blob.lower(), "forbidden Volue logo color present"


def test_resolve_windows_have_distinct_ids(demo_clock):
    from backend.layouts import resolve
    windows = resolve("de_duck_curve", demo_clock)
    ids = [w.window_id for w in windows]
    assert len(set(ids)) == len(ids), "duplicate window_ids"
