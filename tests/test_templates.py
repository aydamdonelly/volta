import json
import pytest
from pathlib import Path


@pytest.fixture
def templates_tmp(tmp_path, monkeypatch):
    import backend.templates as T
    monkeypatch.setattr(T, "TEMPLATES_DIR", tmp_path / "templates")
    yield tmp_path / "templates"


def test_save_template_writes_file(templates_tmp):
    from backend.templates import save_template
    r = save_template("demo_a", {"windows":[],"themes":["t1"],"virtual_now":"2026-04-05T14:00:00Z"})
    assert r["ok"] is True
    p = templates_tmp / "demo_a.json"
    assert p.exists()
    payload = json.loads(p.read_text())
    assert payload["schema_version"] == 1
    assert payload["template_name"] == "demo_a"


def test_restore_template_roundtrip(templates_tmp):
    from backend.templates import save_template, restore_template
    snapshot = {"windows":[{"id":"w1"}],"themes":["t1"],"virtual_now":"2026-04-05T14:00:00Z"}
    save_template("demo_a", snapshot)
    payload = restore_template("demo_a")
    assert payload["canvas_snapshot"] == snapshot


def test_restore_missing_raises(templates_tmp):
    from backend.templates import restore_template
    with pytest.raises(FileNotFoundError):
        restore_template("nonexistent")


@pytest.mark.parametrize("bad_name", ["foo/bar", "foo\\bar", "..", "../etc/passwd", "foo!", "Foo", "", " "])
def test_name_validation_rejects_bad(templates_tmp, bad_name):
    from backend.templates import save_template
    with pytest.raises(ValueError):
        save_template(bad_name, {})


@pytest.mark.parametrize("good_name", ["demo_a", "demo-1", "abc123", "x", "demo_a-1_2"])
def test_name_validation_accepts_good(templates_tmp, good_name):
    from backend.templates import save_template
    save_template(good_name, {})


def test_list_templates(templates_tmp):
    from backend.templates import save_template, list_templates
    save_template("a", {})
    save_template("b", {})
    assert sorted(list_templates()) == ["a", "b"]


def test_schema_v0_migration(templates_tmp):
    from backend.templates import restore_template
    # Write a v0 file manually (no schema_version)
    (templates_tmp).mkdir(parents=True, exist_ok=True)
    p = templates_tmp / "old.json"
    p.write_text(json.dumps({"template_name":"old","windows":[],"themes":[],"virtual_now":""}))
    payload = restore_template("old")
    assert payload["schema_version"] == 1
    assert "canvas_snapshot" in payload
