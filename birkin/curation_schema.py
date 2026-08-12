"""Canonical CurationPlan wire contract."""

from __future__ import annotations

import copy
import json
from importlib import resources
from typing import Any, cast

from .moirai.schema import to_strict


def load_curation_plan_schema() -> dict[str, Any]:
    """Load a fresh copy of the shipped CurationPlan/2 JSON Schema."""
    path = resources.files("birkin").joinpath(
        "schemas/curation-plan-v2.schema.json"
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("CurationPlan schema must be an object")
    return cast(dict[str, Any], value)


def curation_plan_provider_schema() -> dict[str, Any]:
    """Return the canonical contract in OpenAI's strict schema dialect."""
    return copy.deepcopy(to_strict(load_curation_plan_schema()))
