"""Structured, channel-neutral questions for human decisions."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class InvalidAnswer(ValueError):
    """A reply does not match the action's question contract."""


def canonical_digest(value: Any) -> str:
    """SHA-256 of one deterministic, JSON-only contract value."""
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def question_digest(
    *,
    title: str,
    description: str,
    questions: list[dict[str, Any]],
    allow_clarification: bool,
    input_schema_version: int = 1,
) -> str:
    """Bind an answer to the exact question contract shown to a human."""
    return canonical_digest({
        "input_schema_version": input_schema_version,
        "title": title,
        "description": description,
        "questions": questions,
        "allow_clarification": allow_clarification,
    })


def normalize_questions(
    questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a JSON-safe question contract or raise ``ValueError``."""
    if not questions:
        raise ValueError("at least one question is required")

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in questions:
        question_id = str(raw.get("id", "")).strip()
        text = str(raw.get("text", "")).strip()
        if not question_id or len(question_id) > 64:
            raise ValueError("question id must be 1-64 characters")
        if question_id in seen_ids:
            raise ValueError(f"duplicate question id: {question_id}")
        if not text or len(text) > 1_000:
            raise ValueError(f"question {question_id!r} needs text")

        options: list[dict[str, str]] = []
        seen_values: set[str] = set()
        for raw_option in raw.get("options") or []:
            value = str(raw_option.get("value", "")).strip()
            label = str(raw_option.get("label", "")).strip()
            if not value or len(value) > 100 or not label or len(label) > 200:
                raise ValueError(f"question {question_id!r} has an invalid option")
            if value in seen_values:
                raise ValueError(
                    f"question {question_id!r} has duplicate option {value!r}")
            seen_values.add(value)
            options.append({"value": value, "label": label})
        if not options:
            raise ValueError(f"question {question_id!r} needs options")

        recommended = raw.get("recommended")
        if recommended is not None:
            recommended = str(recommended)
            if recommended not in seen_values:
                raise ValueError(
                    f"question {question_id!r} recommends an unknown option")

        question = {
            "id": question_id,
            "text": text,
            "options": options,
            "multiple": bool(raw.get("multiple", False)),
            "required": bool(raw.get("required", True)),
        }
        if recommended is not None:
            question["recommended"] = recommended
        normalized.append(question)
        seen_ids.add(question_id)
    return normalized


def normalize_answers(
    questions: list[dict[str, Any]],
    answers: dict[str, Any],
) -> dict[str, str | list[str]]:
    """Validate and normalize answers against persisted questions."""
    known = {question["id"] for question in questions}
    unknown = set(answers) - known
    if unknown:
        raise InvalidAnswer(f"unknown question: {sorted(unknown)[0]}")

    normalized: dict[str, str | list[str]] = {}
    for question in questions:
        question_id = question["id"]
        raw = answers.get(question_id)
        if raw is None:
            if question.get("required", True):
                raise InvalidAnswer(f"missing answer: {question_id}")
            continue

        allowed = {option["value"] for option in question["options"]}
        if question.get("multiple", False):
            if not isinstance(raw, list) or not raw:
                raise InvalidAnswer(f"answer {question_id!r} must be a list")
            if any(not isinstance(value, str) for value in raw):
                raise InvalidAnswer(f"answer {question_id!r} must contain strings")
            values = raw
            if len(values) != len(set(values)) or any(
                    value not in allowed for value in values):
                raise InvalidAnswer(f"answer {question_id!r} has invalid choices")
            normalized[question_id] = values
        else:
            if not isinstance(raw, str):
                raise InvalidAnswer(f"answer {question_id!r} must be a string")
            value = raw
            if value not in allowed:
                raise InvalidAnswer(f"answer {question_id!r} is invalid")
            normalized[question_id] = value
    return normalized
