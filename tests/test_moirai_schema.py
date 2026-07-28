"""Structured output: a subset validator, a tolerant extractor, one retry.

Two things must hold. A schema the model met is returned as data, and a schema
it missed is reported with a message specific enough to fix on the retry —
"$.findings[0].severity: 'urgent' is not one of low, high" beats "invalid".
"""

from __future__ import annotations

import pytest

from birkin import moirai
from birkin.moirai import journal
from birkin.moirai import schema as S

FINDINGS = {
    "type": "object",
    "required": ["findings"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "severity"],
                "properties": {
                    "title": {"type": "string", "maxLength": 80},
                    "severity": {"type": "string", "enum": ["low", "high"]},
                    "confidence": {"type": "number",
                                   "minimum": 0, "maximum": 1},
                },
            },
        },
    },
}


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


# ---------------- validation ----------------------------------------------

def test_a_conforming_value_passes():
    S.validate({"findings": [{"title": "t", "severity": "low",
                              "confidence": 0.5}]}, FINDINGS)


@pytest.mark.parametrize("value,fragment", [
    ({}, "findings"),
    ({"findings": "no"}, "array"),
    ({"findings": [{"severity": "low"}]}, "title"),
    ({"findings": [{"title": "t", "severity": "urgent"}]}, "허용된 값"),
    ({"findings": [{"title": "x" * 200, "severity": "low"}]}, "최대 80자"),
    ({"findings": [{"title": "t", "severity": "low", "confidence": 2}]},
     "최대 1"),
])
def test_a_mismatch_says_exactly_what_is_wrong(value, fragment):
    with pytest.raises(S.SchemaError, match=fragment):
        S.validate(value, FINDINGS)


def test_the_error_path_points_at_the_offending_field():
    with pytest.raises(S.SchemaError, match=r"\$\.findings\[1\]\.severity"):
        S.validate({"findings": [{"title": "a", "severity": "low"},
                                 {"title": "b", "severity": "nope"}]},
                   FINDINGS)


def test_booleans_are_not_integers():
    with pytest.raises(S.SchemaError):
        S.validate(True, {"type": "integer"})
    S.validate(True, {"type": "boolean"})


def test_a_union_type_accepts_either():
    S.validate("x", {"type": ["string", "null"]})
    S.validate(None, {"type": ["string", "null"]})
    with pytest.raises(S.SchemaError):
        S.validate(5, {"type": ["string", "null"]})


def test_unknown_keywords_are_ignored_rather_than_failing():
    """A validator stricter than the model can see rejects good answers."""
    S.validate({"a": 1}, {"type": "object", "$comment": "hi",
                          "additionalProperties": False,
                          "patternProperties": {"^a": {}}})


# ---------------- extraction ----------------------------------------------

@pytest.mark.parametrize("text,expect", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('```\n{"a": 1}\n```', {"a": 1}),
    ('네, 결과입니다: {"a": 1} — 이상입니다', {"a": 1}),
    ('[1, 2, 3]', [1, 2, 3]),
    ('설명\n\n[{"a": 1}]\n\n끝', [{"a": 1}]),
])
def test_extract_finds_json_through_prose_and_fences(text, expect):
    assert S.extract(text) == expect


def test_extract_is_not_fooled_by_braces_inside_strings():
    assert S.extract('{"a": "use {curly} braces"}') == {
        "a": "use {curly} braces"}


@pytest.mark.parametrize("text", ["", "no json here", "{broken", "```\n```"])
def test_extract_returns_none_rather_than_guessing(text):
    assert S.extract(text) is None


def test_decode_rejects_a_reply_with_no_json():
    with pytest.raises(S.SchemaError, match="JSON을 찾지 못했습니다"):
        S.decode("죄송합니다, 잘 모르겠습니다", FINDINGS)


def test_decode_without_a_schema_passes_text_through():
    assert S.decode("plain text", None) == "plain text"


# ---------------- engine integration --------------------------------------

def _script(tmp_path, body):
    p = tmp_path / "s.py"
    p.write_text(body, encoding="utf-8")
    return moirai.load_script(p)


SCHEMA_SCRIPT = '''
SCHEMA = {"type": "object", "required": ["answer"],
          "properties": {"answer": {"type": "string"}}}

meta = {"name": "structured", "roles": {"w": {"default": "claude:haiku"}}}

def main(m):
    return m.agent("질문", role="w", schema=SCHEMA)
'''


def test_a_schema_answer_comes_back_as_data(tmp_path):
    def spawn(prompt, binding, opts, cfg, *, timeout=900.0):
        return '```json\n{"answer": "서울"}\n```'

    out = moirai.run_script(_script(tmp_path, SCHEMA_SCRIPT), cfg={},
                            spawn=spawn)
    assert out["result"] == {"answer": "서울"}


def test_the_schema_is_put_in_the_prompt_for_providers_that_cannot_enforce_it(
        tmp_path, monkeypatch):
    seen = {}

    def fake_get_completer(provider, **kw):
        seen["schema_arg"] = kw.get("schema")

        def complete(prompt):
            seen["prompt"] = prompt
            return '{"answer": "ok"}'
        return complete

    monkeypatch.setattr("birkin.providers.get_completer", fake_get_completer)
    moirai.run_script(_script(tmp_path, SCHEMA_SCRIPT), cfg={})
    assert seen["schema_arg"] is None, "claude cannot enforce a schema natively"
    assert "JSON 스키마" in seen["prompt"]


def test_codex_gets_the_schema_natively_and_no_prompt_boilerplate(
        tmp_path, monkeypatch):
    seen = {}
    body = SCHEMA_SCRIPT.replace("claude:haiku", "codex:gpt-5.6-sol")

    def fake_get_completer(provider, **kw):
        seen["schema_arg"] = kw.get("schema")

        def complete(prompt):
            seen["prompt"] = prompt
            return '{"answer": "ok"}'
        return complete

    monkeypatch.setattr("birkin.providers.get_completer", fake_get_completer)
    moirai.run_script(_script(tmp_path, body), cfg={})
    assert seen["schema_arg"] is not None, "codex enforces the schema itself"
    assert "JSON 스키마" not in seen["prompt"]


def test_a_miss_is_retried_once_with_the_complaint_attached(tmp_path):
    attempts = []

    def spawn_via_completer(prompt, binding, opts, cfg, *, timeout=900.0):
        raise AssertionError("should not be used")

    seen = {}

    def fake_get_completer(provider, **kw):
        def complete(prompt):
            attempts.append(prompt)
            if len(attempts) == 1:
                return "그냥 텍스트입니다"
            seen["retry_prompt"] = prompt
            return '{"answer": "두번째"}'
        return complete

    import birkin.providers as providers
    original = providers.get_completer
    providers.get_completer = fake_get_completer
    try:
        out = moirai.run_script(_script(tmp_path, SCHEMA_SCRIPT), cfg={})
    finally:
        providers.get_completer = original

    assert len(attempts) == 2
    assert "맞지 않았습니다" in seen["retry_prompt"]
    assert out["result"] == {"answer": "두번째"}


def test_two_misses_fail_the_agent_but_not_the_run(tmp_path):
    import birkin.providers as providers

    def fake_get_completer(provider, **kw):
        return lambda prompt: "여전히 텍스트"

    original = providers.get_completer
    providers.get_completer = fake_get_completer
    try:
        out = moirai.run_script(_script(tmp_path, SCHEMA_SCRIPT), cfg={})
    finally:
        providers.get_completer = original

    assert out["status"] == "completed" and out["result"] is None
    assert "스키마" in journal.run_calls(out["run_id"])[0]["error"]


# ---------------- the strict dialect codex requires ------------------------

def test_to_strict_adds_what_openai_demands():
    """codex rejects a plain schema outright: 'additionalProperties is
    required to be supplied and to be false'. Found by a live call."""
    src = {"type": "object", "required": ["a"],
           "properties": {"a": {"type": "string"},
                          "b": {"type": "number"}}}
    strict = S.to_strict(src)
    assert strict["additionalProperties"] is False
    assert set(strict["required"]) == {"a", "b"}, "strict mode requires all"
    assert strict["properties"]["b"]["type"] == ["number", "null"], (
        "an optional field survives as required-but-nullable")
    assert strict["properties"]["a"]["type"] == "string", "required unchanged"


def test_to_strict_leaves_the_callers_schema_alone():
    src = {"type": "object", "properties": {"a": {"type": "string"}}}
    S.to_strict(src)
    assert "additionalProperties" not in src and "required" not in src


def test_to_strict_reaches_nested_objects_and_arrays():
    src = {"type": "object", "properties": {
        "items": {"type": "array", "items": {
            "type": "object", "properties": {"x": {"type": "string"}}}}}}
    strict = S.to_strict(src)
    assert strict["properties"]["items"]["items"]["additionalProperties"] is False


def test_relax_drops_the_nulls_the_dialect_invented():
    src = {"type": "object", "required": ["a"],
           "properties": {"a": {"type": "string"},
                          "b": {"type": "number"}}}
    got = S.relax({"a": "x", "b": None}, src)
    assert got == {"a": "x"}
    S.validate(got, src)          # and it now fits the caller's own schema


def test_relax_keeps_a_null_the_caller_actually_allowed():
    src = {"type": "object",
           "properties": {"a": {"type": ["string", "null"]}}}
    assert S.relax({"a": None}, src) == {"a": None}


def test_relax_walks_arrays_of_objects():
    src = {"type": "array", "items": {
        "type": "object", "required": ["a"],
        "properties": {"a": {"type": "string"}, "b": {"type": "number"}}}}
    assert S.relax([{"a": "x", "b": None}], src) == [{"a": "x"}]


def test_codex_is_handed_the_strict_dialect_not_the_raw_schema(
        tmp_path, monkeypatch):
    seen = {}
    body = SCHEMA_SCRIPT.replace("claude:haiku", "codex:gpt-5.6-sol")

    def fake_get_completer(provider, **kw):
        seen["schema"] = kw.get("schema")
        return lambda prompt: '{"answer": "ok"}'

    monkeypatch.setattr("birkin.providers.get_completer", fake_get_completer)
    moirai.run_script(_script(tmp_path, body), cfg={})
    assert seen["schema"]["additionalProperties"] is False
