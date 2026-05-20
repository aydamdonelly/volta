"""Templates — POSIX-atomic JSON writes for save/restore. Per r2-backend §7."""
from __future__ import annotations
import json, logging, os, re, tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
TEMPLATES_DIR = Path("data/templates")
_VALID_NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}$")

log = logging.getLogger("volta.templates")


def _validate_name(name: str) -> None:
    if not _VALID_NAME_RE.match(name):
        raise ValueError(f"invalid template name: {name!r} (must match [a-z0-9_-]{{1,64}})")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """POSIX-atomic write: tempfile in same dir → flush + fsync → os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        prefix=path.name + ".",
        suffix=".tmp",
    ) as tf:
        json.dump(payload, tf, ensure_ascii=False, indent=2, sort_keys=True)
        tf.flush()
        os.fsync(tf.fileno())
        tmp_name = tf.name
    os.replace(tmp_name, str(path))


def save_template(name: str, canvas_snapshot: dict[str, Any]) -> dict:
    """Save a template atomically. Schema-versioned via `schema_version`."""
    _validate_name(name)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "template_name": name,
        "canvas_snapshot": canvas_snapshot,
    }
    path = TEMPLATES_DIR / f"{name}.json"
    _atomic_write_json(path, payload)
    return {"ok": True, "name": name}


def restore_template(name: str) -> dict[str, Any]:
    """Load a template. Raises FileNotFoundError if missing (main.py wraps to 404)."""
    _validate_name(name)
    path = TEMPLATES_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"template not found: {name!r}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    ver = payload.get("schema_version", 0)
    if ver < SCHEMA_VERSION:
        payload = _migrate_template(payload, ver, SCHEMA_VERSION)
    elif ver > SCHEMA_VERSION:
        log.warning("template %s has schema_version=%d > current=%d", name, ver, SCHEMA_VERSION)
    return payload


def list_templates() -> list[str]:
    if not TEMPLATES_DIR.exists():
        return []
    return sorted(p.stem for p in TEMPLATES_DIR.glob("*.json"))


def _migrate_template(payload: dict, from_version: int, to_version: int) -> dict:
    """Schema migration: v0 → v1 lifts flat windows/themes/virtual_now into canvas_snapshot."""
    if from_version == 0:
        payload["schema_version"] = 1
        if "canvas_snapshot" not in payload and "windows" in payload:
            payload["canvas_snapshot"] = {
                "windows": payload.get("windows", []),
                "themes": payload.get("themes", []),
                "virtual_now": payload.get("virtual_now", ""),
            }
    return payload
