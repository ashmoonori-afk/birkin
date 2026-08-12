"""Structured agent output, without a schema library.

Three paths, because the providers differ in what they can promise:

- **codex** enforces a JSON schema natively (``codex exec --output-schema``),
  so the answer is already the right shape.
- **claude / anthropic / everything else** get the schema in the prompt, and
  the reply is mined for JSON, validated, and asked once more with the
  complaint attached if it did not fit.

Validation is a deliberate subset of JSON Schema — type, required, properties,
items, enum, minimum/maximum, maxLength — which is all a workflow contract
needs, and it keeps ``dependencies = []`` true. Anything unrecognised in a
schema is ignored rather than treated as a failure: a stricter validator than
the model can see is a validator that rejects good answers.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

_FENCED = re.compile(r"```(?:json)?\s*\n(.*?)```", re.S)


class SchemaError(ValueError):
    """The value does not fit the contract. The message is fed back to the model."""


# -- validation ------------------------------------------------------------

def validate(
    value: Any,
    schema: dict,
    *,
    path: str = "$",
    strict_contract: bool = False,
) -> None:
    """Raise :class:`SchemaError` describing the first thing that does not fit."""
    if not isinstance(schema, dict):
        return

    expected = schema.get("type")
    if expected and not _type_ok(value, expected):
        raise SchemaError(
            f"{path}: {_name(expected)} 가 필요한데 {_kind(value)} 입니다")

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(
            f"{path}: {value!r} 는 허용된 값이 아닙니다 "
            f"({', '.join(map(str, schema['enum']))})")
    if strict_contract and "const" in schema and value != schema["const"]:
        raise SchemaError(
            f"{path}: {schema['const']!r} 이어야 합니다")

    if isinstance(value, str):
        limit = schema.get("maxLength")
        if isinstance(limit, int) and len(value) > limit:
            raise SchemaError(f"{path}: 최대 {limit}자인데 {len(value)}자입니다")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        low, high = schema.get("minimum"), schema.get("maximum")
        if low is not None and value < low:
            raise SchemaError(f"{path}: {value} < 최소 {low}")
        if high is not None and value > high:
            raise SchemaError(f"{path}: {value} > 최대 {high}")

    if isinstance(value, dict):
        for key in schema.get("required", []) or []:
            if key not in value:
                raise SchemaError(f"{path}: 필수 필드 {key!r} 가 없습니다")
        props = schema.get("properties") or {}
        if strict_contract and schema.get("additionalProperties") is False:
            extras = set(value) - set(props)
            if extras:
                key = min(extras)
                raise SchemaError(f"{path}: 알 수 없는 필드 {key!r}")
        for key, sub in props.items():
            if key in value:
                validate(
                    value[key],
                    sub,
                    path=f"{path}.{key}",
                    strict_contract=strict_contract,
                )

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(value):
                validate(
                    item,
                    item_schema,
                    path=f"{path}[{i}]",
                    strict_contract=strict_contract,
                )


def _type_ok(value: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        return any(_type_ok(value, e) for e in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True                                   # unknown type: don't fight it


def _name(expected: Any) -> str:
    return "|".join(expected) if isinstance(expected, list) else str(expected)


def _kind(value: Any) -> str:
    return {dict: "object", list: "array", str: "string", bool: "boolean",
            int: "integer", float: "number", type(None): "null"
            }.get(type(value), type(value).__name__)


# -- extraction ------------------------------------------------------------

def extract(text: str) -> Optional[Any]:
    """Find the JSON value in a reply that may be wrapped in prose or fences.

    Fenced blocks first (a model that was asked for JSON usually fences it),
    then the first balanced object or array. Same approach as the curation
    plan extractor, which has survived four provider families.
    """
    if not text:
        return None
    raw = text.strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass
    for candidate in _FENCED.findall(raw):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    for candidate in _balanced(raw):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _balanced(text: str) -> list[str]:
    """Balanced {...} / [...] spans, outermost and earliest first.

    One pass over both bracket kinds, because scanning objects before arrays
    finds the inner {"a": 1} of `[{"a": 1}]` and hands back a fragment of the
    answer instead of the answer.
    """
    spans: list[tuple[int, int]] = []
    stack: list[tuple[str, int]] = []
    in_str = esc = False
    pairs = {"{": "}", "[": "]"}
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in pairs:
            stack.append((ch, i))
        elif ch in ("}", "]") and stack:
            opener, start = stack[-1]
            if pairs[opener] == ch:
                stack.pop()
                if not stack:
                    spans.append((start, i + 1))
    # earliest first, and for a tie the longer (outer) span wins
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    return [text[a:b] for a, b in spans]


# -- prompting -------------------------------------------------------------

def instruction(schema: dict) -> str:
    """The block appended for providers that cannot enforce a schema."""
    return (
        "\n\n---\n"
        "답은 아래 JSON 스키마에 맞는 **JSON 하나만** 출력하세요. "
        "설명·머리말·코드펜스 없이 JSON 그 자체만.\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=1)}\n")


def retry_instruction(problem: str) -> str:
    """What to say when the first attempt did not fit."""
    return (f"\n\n직전 답이 스키마에 맞지 않았습니다: {problem}\n"
            "같은 스키마로 JSON 하나만 다시 출력하세요.")


def decode(text: str, schema: Optional[dict]) -> Any:
    """Parse and validate, or raise :class:`SchemaError` with the reason."""
    if not schema:
        return text
    value = extract(text)
    if value is None:
        raise SchemaError("응답에서 JSON을 찾지 못했습니다")
    validate(value, schema)
    return value


# -- provider dialects -----------------------------------------------------

def to_strict(schema: Any) -> Any:
    """Rewrite a schema into OpenAI's strict structured-output dialect.

    codex enforces schemas through that dialect, which demands more than plain
    JSON Schema: every object must set ``additionalProperties: false`` and must
    list *every* property in ``required``. Handing it an ordinary schema fails
    the request outright ("'additionalProperties' is required to be supplied
    and to be false"), which is how this was found — a live codex call.

    Optional fields survive the translation by becoming required-but-nullable,
    the shape OpenAI itself recommends. :func:`relax` undoes that afterwards so
    the script sees the schema it wrote, not the dialect.
    """
    if isinstance(schema, list):
        return [to_strict(s) for s in schema]
    if not isinstance(schema, dict):
        return schema

    out = {k: to_strict(v) if k in ("items", "properties") else v
           for k, v in schema.items()}
    if isinstance(out.get("properties"), dict):
        out["properties"] = {k: to_strict(v)
                             for k, v in out["properties"].items()}
    if out.get("type") == "object" or "properties" in out:
        props = out.get("properties") or {}
        out["additionalProperties"] = False
        required = list(out.get("required") or [])
        for key, sub in props.items():
            if key in required:
                continue
            required.append(key)
            if isinstance(sub, dict) and "type" in sub:
                kinds = sub["type"]
                kinds = kinds if isinstance(kinds, list) else [kinds]
                if "null" not in kinds:
                    sub["type"] = kinds + ["null"]
        out["required"] = required
    return out


def relax(value: Any, schema: Any) -> Any:
    """Drop the nulls :func:`to_strict` had to invent, per the original schema.

    A field the script marked optional comes back as ``null`` rather than
    absent; leaving it in would fail validation against the script's own
    schema, which never allowed null.
    """
    if isinstance(schema, dict) and isinstance(value, list):
        item = schema.get("items")
        if isinstance(item, dict):
            return [relax(v, item) for v in value]
        return value
    if not (isinstance(schema, dict) and isinstance(value, dict)):
        return value
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    out = {}
    for key, val in value.items():
        sub = props.get(key)
        if val is None and key not in required and _forbids_null(sub):
            continue
        out[key] = relax(val, sub) if isinstance(sub, dict) else val
    return out


def _forbids_null(sub: Any) -> bool:
    if not isinstance(sub, dict) or "type" not in sub:
        return True
    kinds = sub["type"]
    kinds = kinds if isinstance(kinds, list) else [kinds]
    return "null" not in kinds
