from __future__ import annotations
import json
from importlib.resources import files
from typing import cast
def load_document_ir_schema()->dict[str,object]:
    loaded = cast(
        object,
        json.loads(
            files("birkin.schemas")
            .joinpath("document-ir-v1.schema.json")
            .read_text(encoding="utf-8")
        ),
    )
    if not isinstance(loaded, dict):
        raise ValueError("DocumentIR schema must be a JSON object")
    object_map = cast(dict[object, object], loaded)
    return {str(key): value for key, value in object_map.items()}
