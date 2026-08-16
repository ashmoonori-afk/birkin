"""Closed JSON schemas for active-content-bound patch requests."""

SHA256_SCHEMA: dict[str, object] = {
    "type": "string",
    "pattern": "^[0-9a-f]{64}$",
}

ACTIVE_CONTENT_CONSENT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "source_sha256": SHA256_SCHEMA,
        "inventory_sha256": SHA256_SCHEMA,
        "preservation_mode": {
            "type": "string",
            "enum": ["preserve_exact"],
        },
    },
    "required": [
        "source_sha256",
        "inventory_sha256",
        "preservation_mode",
    ],
    "additionalProperties": False,
}

PATCH_OPERATION_SCHEMA: dict[str, object] = {
    "oneOf": [
        {
            "type": "object",
            "properties": {"field": {"type": "string"}, "value": {}},
            "required": ["field", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"cell": {"type": "string"}, "value": {}},
            "required": ["cell", "value"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "placeholder_idx": {"type": "integer", "minimum": 0},
                "value": {"type": "string"},
            },
            "required": ["placeholder_idx", "value"],
            "additionalProperties": False,
        },
    ]
}
