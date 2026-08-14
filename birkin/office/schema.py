from __future__ import annotations
import json
from importlib.resources import files
from typing import Any
def load_document_ir_schema()->dict[str,Any]:
    return json.loads(files("birkin.schemas").joinpath("document-ir-v1.schema.json").read_text(encoding="utf-8"))
