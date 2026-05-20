"""Unit tests for the search-first R(name) curve resolver in scripts/prepull.py.

Pattern is verified live in API_CONTRACT §1; here we only assert the dispatch
logic in isolation (no Volue session, no network).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from scripts.prepull import R


def test_R_search_first_returns_exact_match():
    session = MagicMock()
    hit_a = MagicMock()
    hit_a.name = "pri de spot €/mwh cet h a"
    hit_b = MagicMock()
    hit_b.name = "pri de spot something else"
    session.search.return_value = [hit_a, hit_b]
    r = R(session, "pri de spot €/mwh cet h a")
    assert r is hit_a


def test_R_strips_weather_run_on_empty_search():
    session = MagicMock()
    hit_a = MagicMock()
    hit_a.name = "pro de spv mwh/h cet min15 a"
    session.search.side_effect = [[], [hit_a]]  # empty first, hit on stripped
    r = R(session, "pro de spv ec00 mwh/h cet min15 a")
    assert r is hit_a


def test_R_falls_back_to_get_curve_on_no_hits():
    session = MagicMock()
    session.search.return_value = []
    curve = MagicMock()
    session.get_curve.return_value = curve
    r = R(session, "some name")
    assert r is curve
    session.get_curve.assert_called_once_with(name="some name")
