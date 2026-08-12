from __future__ import annotations

from birkin import curation_schema
from birkin.curation_contract import OPS, PLAN_VERSION


def test_canonical_schema_defines_the_current_machine_contract() -> None:
    schema = curation_schema.load_curation_plan_schema()

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("curation-plan-v2.schema.json")
    assert schema["properties"]["plan_version"]["const"] == PLAN_VERSION == 2
    operation = schema["properties"]["ops"]["items"]
    assert set(operation["properties"]["op"]["enum"]) == OPS
    assert {"aliases", "queries", "xlang"} <= set(operation["properties"])
    assert schema["additionalProperties"] is False
    assert operation["additionalProperties"] is False


def test_provider_schema_is_strict_without_mutating_canonical_schema() -> None:
    canonical = curation_schema.load_curation_plan_schema()
    provider = curation_schema.curation_plan_provider_schema()
    operation = provider["properties"]["ops"]["items"]

    assert canonical["properties"]["ops"]["items"].get("required") == ["op"]
    assert set(operation["required"]) == set(operation["properties"])
    assert operation["properties"]["aliases"]["type"] == ["array", "null"]
    assert provider["properties"]["plan_version"]["const"] == 2
    assert provider["properties"]["summary"]["type"] == "string"
    assert "summary" in provider["required"]


def test_v2_parser_rejects_unknown_operations_and_extra_fields() -> None:
    from birkin import curation_prompt

    unknown = (
        '{"plan_version":2,"ops":[{"op":"delete","reason":"no"}],'
        '"summary":"unsafe"}'
    )
    extra = (
        '{"plan_version":2,"ops":[],"summary":"unsafe","surprise":true}'
    )

    assert curation_prompt.extract_plan(unknown)["ops"] == []
    assert curation_prompt.extract_plan(extra)["ops"] == []


def test_prompt_embeds_the_canonical_schema() -> None:
    import json

    from birkin import curation_prompt

    marker = "matching this canonical\nschema:\n\n"
    prompt = curation_prompt.build_plan_prompt(
        {"notes": [], "existing_zones": [], "stale_candidates": []}
    )
    encoded = prompt.split(marker, 1)[1].split("\n\nEach op", 1)[0]

    assert json.loads(encoded) == curation_schema.load_curation_plan_schema()
