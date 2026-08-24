"""Trusted prompt contract for claims about local paths and permissions."""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Final

OPEN_TAG: Final = "<local-environment-evidence-policy>"
CLOSE_TAG: Final = "</local-environment-evidence-policy>"
_INSTRUCTIONS: Final = (
    (
        "observe-host-before-path-claim",
        "Use current tool output to establish the host and every filesystem "
        + "path you report. Treat remembered or transcript paths as unverified; "
        + "never substitute a path from another operating system.",
    ),
    (
        "probe-write-before-permission-claim",
        "Before claiming a target is not writable, use an available tool to "
        + "perform a reversible write probe within that target's directory. "
        + "Report the observed result before making a permission claim.",
    ),
    (
        "probe-temporary-entry-only",
        "Probe only through a uniquely named temporary entry created inside "
        + "the target directory. Never create, modify, or delete an existing "
        + "path; remove only the temporary entry created by the probe.",
    ),
    (
        "classify-write-failure-source",
        "Classify a failed probe as a sandbox, active route, missing tool, "
        + "approval requirement, or operating-system permission result from "
        + "the observed evidence. Never relabel one restriction as another.",
    ),
    (
        "preserve-requested-scope",
        "Keep the user's requested outcome and application scope binding. Do "
        + "not replace an applied change with a workspace draft or narrower "
        + "task. If blocked, report the exact missing capability or approval "
        + "and do not claim completion.",
    ),
    (
        "separate-user-assistant-identity",
        "Keep user-profile facts separate from assistant persona facts. A "
        + "name assigned to the assistant is not the user's name; resolve roles "
        + "from explicit current-conversation evidence before writing either.",
    ),
)
_REQUIRED_RULES: Final = tuple(name for name, _instruction in _INSTRUCTIONS)


@dataclass(frozen=True, slots=True)
class LocalEnvironmentEvidence:
    """Current host facts and stable local-operation rules."""

    host_os: str
    home: str
    required_rules: tuple[str, ...]


def collect(
    *,
    host_os: str | None = None,
    home: Path | None = None,
) -> LocalEnvironmentEvidence:
    """Collect current host facts without inferring filesystem permissions."""
    return LocalEnvironmentEvidence(
        host_os=host_os or platform.system(),
        home=str(home if home is not None else Path.home()),
        required_rules=_REQUIRED_RULES,
    )


def render(
    *,
    host_os: str | None = None,
    home: Path | None = None,
) -> str:
    """Render current host facts and binding local-operation rule identifiers."""
    evidence = collect(host_os=host_os, home=home)
    payload = {
        "host_os": evidence.host_os,
        "home": evidence.home,
        "required_rules": list(evidence.required_rules),
        "instructions": dict(_INSTRUCTIONS),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    prompt_safe = encoded.replace("<", "\\u003c").replace(">", "\\u003e")
    return (
        f"{OPEN_TAG}\n"
        f"{prompt_safe}\n"
        f"{CLOSE_TAG}"
    )


def strip_markers(text: str) -> str:
    """Remove local-policy delimiters from lower-authority prompt content."""
    while True:
        stripped = text.replace(OPEN_TAG, "").replace(CLOSE_TAG, "")
        if stripped == text:
            return stripped
        text = stripped


def seal(system_prompt: str) -> str:
    """Append one authoritative policy after lower-authority prompt content."""
    policy = render()
    without_policy = strip_markers(system_prompt.replace(policy, "")).strip()
    if not without_policy:
        return policy
    return f"{without_policy}\n\n{policy}"
