"""Versioned aliases for the verified built-in business templates."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path

from birkin import config, store

BASES = {
    "weekly_report": {"version": "1.0", "required": ["title", "period", "summary"]},
    "meeting_notes": {"version": "1.0", "required": ["title", "date", "summary"]},
    "work_proposal": {"version": "1.0", "required": ["title", "problem", "proposal"]},
}
TONES = {"plain", "concise", "formal"}


def _read() -> dict[str, dict[str, object]]:
    raw = store._read_json(config.office_templates_path(), {})
    return {str(key): dict(value) for key, value in raw.items() if isinstance(value, dict)} if isinstance(raw, dict) else {}


def _write(records: Mapping[str, object]) -> None:
    store._write_json(config.office_templates_path(), dict(records))


def _preferences(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) - {"tone", "include_optional"}:
        raise ValueError("preferences may contain only tone and include_optional; document body is never saved")
    tone = value.get("tone", "plain")
    optional = value.get("include_optional", True)
    if tone not in TONES or not isinstance(optional, bool):
        raise ValueError("invalid template preferences")
    return {"tone": tone, "include_optional": optional}


def apply_approved(payload: dict[str, object]) -> str:
    action = str(payload.get("action", ""))
    workspace = str(Path(str(payload.get("workspace", "."))).resolve())
    with store.file_lock(config.office_templates_path()):
        records = _read()
        if action == "clone":
            base = str(payload.get("base", ""))
            if base not in BASES:
                raise ValueError("unknown verified base template")
            record: dict[str, object] = {
                "id": uuid.uuid4().hex,
                "name": str(payload.get("name", "")).strip(),
                "base": base,
                "base_version": BASES[base]["version"],
                "version": 1,
                "scope": payload.get("scope", "current_work"),
                "workspace": workspace,
                "preferences": _preferences(payload.get("preferences", {})),
            }
            if not record["name"] or record["scope"] not in {"current_work", "global"}:
                raise ValueError("name and valid scope are required")
            records[str(record["id"])] = record
        else:
            template_id = str(payload.get("template_id", ""))
            record = records.get(template_id) or {}
            if record.get("version") != payload.get("version"):
                raise ValueError("template version changed; preview and approve again")
            if action == "rename":
                name = str(payload.get("name", "")).strip()
                if not name:
                    raise ValueError("name is required")
                record["name"] = name
            elif action == "update":
                record["preferences"] = _preferences(payload.get("preferences"))
            elif action == "restore":
                record["preferences"] = _preferences({})
            else:
                raise ValueError("unsupported template action")
            record["version"] = int(record["version"]) + 1
            records[template_id] = record
        _write(records)
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


def list_templates(workspace: object) -> dict[str, object]:
    root = str(Path(str(workspace)).resolve())
    saved = [deepcopy(item) for item in _read().values() if item.get("scope") == "global" or item.get("workspace") == root]
    return {"verified_bases": deepcopy(BASES), "saved": sorted(saved, key=lambda item: str(item["name"]))}


def resolve(template_id: object, version: object, values: object, sources: object, workspace: object) -> dict[str, object]:
    record = next((item for item in list_templates(workspace)["saved"] if item["id"] == template_id), None)
    if record is None or record.get("version") != version:
        raise ValueError("template is unavailable or changed; preview the current version")
    if not isinstance(values, Mapping) or not isinstance(sources, Mapping):
        raise ValueError("values and sources must be objects")
    return {
        "content": {"business_template": {
            "name": record["base"], "version": record["base_version"],
            "values": dict(values), "sources": dict(sources),
        }},
        "saved_template": deepcopy(record),
    }


__all__ = ["BASES", "apply_approved", "list_templates", "resolve"]
