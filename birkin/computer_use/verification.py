"""Typed post-mutation effect verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import ObservedElement


@dataclass(frozen=True, slots=True)
class Verification:
    effect: str
    refusal_code: str | None
    observed: object | None


def verify_effect(
    predicted: dict[str, Any],
    *,
    before: ObservedElement | None,
    after: ObservedElement | None,
) -> Verification:
    if after is None:
        return Verification(
            "unverifiable",
            "verification_unavailable",
            None,
        )
    property_name = str(predicted.get("property", ""))
    if property_name not in {"value", "name", "role"}:
        return Verification(
            "unverifiable",
            "verification_unsupported",
            None,
        )
    observed = getattr(after, property_name)
    operation = predicted.get("operation")
    if operation == "equals":
        confirmed = observed == predicted.get("value")
    elif operation == "changes":
        confirmed = before is not None and observed != getattr(before, property_name)
    elif operation == "appears":
        confirmed = observed not in (None, "", False)
    elif operation == "disappears":
        confirmed = observed in (None, "", False)
    else:
        return Verification(
            "unverifiable",
            "verification_unsupported",
            observed,
        )
    if confirmed:
        return Verification("confirmed", None, observed)
    return Verification("suspected_noop", "verification_failed", observed)
