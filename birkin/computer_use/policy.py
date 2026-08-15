"""Native-metadata policy decisions for desktop mutations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import ObservedElement

_SENSITIVE = {
    "password",
    "secret",
    "two_factor",
    "payment",
    "permission_dialog",
    "system_dialog",
}
_RISKY = {
    "logout",
    "lock",
    "delete",
    "security_settings",
    "privilege_elevation",
}
_SHELL_PATTERN = re.compile(r"(?:[;&|`$<>]|\brm\s+-|\bsudo\b)", re.IGNORECASE)
_SHELL_CAPABLE_ROLES = {
    "document",
    "terminal",
    "textarea",
}


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    status: str
    refusal_code: str | None


def classify_mutation(
    element: ObservedElement,
    request: dict[str, Any],
) -> PolicyDecision:
    """Classify only trusted request fields and native element metadata."""
    category = element.sensitive_category
    if category in _SENSITIVE:
        return PolicyDecision("action_needed", "sensitive_target_blocked")
    if category in _RISKY:
        return PolicyDecision(
            "approval_required",
            "risky_action_approval_required",
        )
    if (
        request.get("action") == "type"
        and element.role.casefold().removeprefix("ax").replace("_", "")
        in _SHELL_CAPABLE_ROLES
        and _SHELL_PATTERN.search(str(request.get("text", "")))
    ):
        return PolicyDecision(
            "approval_required",
            "risky_action_approval_required",
        )
    return PolicyDecision("allowed", None)


_SEMANTIC_ACTIONS = {
    "click": "press",
    "double_click": "double_click",
    "right_click": "show_menu",
    "middle_click": "middle_click",
    "drag": "drag",
    "scroll": "scroll",
    "type": "set_value",
    "key": "key",
}


def semantic_action_supported(
    element: ObservedElement,
    action: str,
) -> bool:
    required = _SEMANTIC_ACTIONS.get(action)
    return required is not None and required in element.supported_actions


def command_value(request: dict[str, Any]) -> object | None:
    action = request.get("action")
    if action == "type":
        return request.get("text")
    if action == "key":
        chord = request.get("chord")
        return chord.get("key") if isinstance(chord, dict) else None
    return request.get("direction") if action == "scroll" else None
