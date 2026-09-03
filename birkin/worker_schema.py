"""JSON Schema for structured natural-language worker requests."""

from __future__ import annotations

from .worker_request import JsonObject


def _const(value: str) -> JsonObject:
    return {"type": "string", "const": value}


def _object(properties: JsonObject, required: list[str]) -> JsonObject:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def input_schema() -> JsonObject:
    text: JsonObject = {"type": "string", "minLength": 1, "maxLength": 4000}
    optional_text: JsonObject = {"type": "string", "maxLength": 4000, "default": ""}
    scope: JsonObject = {
        "type": "string",
        "enum": ["local", "global"],
        "default": "global",
    }
    variants: list[JsonObject] = [
        _object(
            {
                "worker": _const("moirai"),
                "action": _const("run"),
                "script": text,
                "task": text,
            },
            ["worker", "action", "script", "task"],
        ),
        _object(
            {
                "worker": _const("moirai"),
                "action": _const("list"),
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10,
                },
            },
            ["worker", "action"],
        ),
        *[
            _object(
                {
                    "worker": _const("moirai"),
                    "action": _const(action),
                    "run_id": text,
                },
                ["worker", "action", "run_id"],
            )
            for action in ("status", "resume")
        ],
        _object(
            {
                "worker": _const("morpheus"),
                "action": _const("run"),
                "dry_run": {"type": "boolean", "default": False},
            },
            ["worker", "action"],
        ),
        *[
            _object(
                {
                    "worker": _const("harness"),
                    "action": _const(action),
                    "scope": scope,
                },
                ["worker", "action"],
            )
            for action in ("show", "history")
        ],
        *[
            _object(
                {
                    "worker": _const("harness"),
                    "action": _const(action),
                    "target": text,
                    "scope": scope,
                },
                ["worker", "action", "target"],
            )
            for action in ("rollback", "export")
        ],
        _object(
            {
                "worker": _const("harness"),
                "action": _const("refine"),
                "target": optional_text,
                "scope": scope,
            },
            ["worker", "action"],
        ),
        _object({"worker": _const("odyssey"), "goal": text}, ["worker", "goal"]),
        _object(
            {
                "worker": _const("neurosis"),
                "idea": text,
                "resolution": {
                    "type": "string",
                    "enum": ["quick", "standard", "deep"],
                    "default": "standard",
                },
            },
            ["worker", "idea"],
        ),
        _object(
            {
                "worker": _const("daedalus"),
                "action": _const("create"),
                "slug": text,
                "root": text,
            },
            ["worker", "action", "slug"],
        ),
        _object(
            {
                "worker": _const("daedalus"),
                "action": _const("refresh"),
                "slug": text,
                "root": text,
                "token": text,
            },
            ["worker", "action", "slug", "token"],
        ),
        _object(
            {"worker": _const("daedalus"), "action": _const("show"), "slug": text},
            ["worker", "action", "slug"],
        ),
        _object(
            {
                "worker": _const("daedalus"),
                "action": _const("note"),
                "slug": text,
                "text": text,
                "refs": {"type": "array", "items": text, "default": []},
            },
            ["worker", "action", "slug", "text"],
        ),
        _object(
            {"worker": _const("daedalus"), "action": _const("profile")},
            ["worker", "action"],
        ),
    ]
    return {"oneOf": variants}
