"""Filesystem persistence for automatic role profiles."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Literal, NoReturn, Protocol

from .atomic import atomic_write

PROFILE_DESCRIPTIONS = {
    "user": "User characteristics and stable personal context.",
    "preferences": "User preferences and favored choices.",
    "soul": "Conversation style and interaction guidance.",
    "workflow": "User work process and execution guidance.",
    "automation": "User workflow automation guidance.",
}

_PROFILE_TITLES = {
    "user": "User",
    "preferences": "Preferences",
    "soul": "Soul",
    "workflow": "Workflow",
    "automation": "Automation",
}
_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class ProfileProposalView(Protocol):
    """Read-only fields needed to persist one validated proposal."""

    @property
    def profile(self) -> str: ...

    @property
    def action(self) -> Literal["add", "replace", "remove"]: ...

    @property
    def content(self) -> str: ...

    @property
    def old_text(self) -> str: ...


def _assert_never(value: NoReturn) -> NoReturn:
    raise AssertionError(f"unreachable profile action: {value!r}")


def vault_lock(vault: Path) -> threading.Lock:
    """Return the process-local lock protecting one profile vault."""
    key = vault.resolve()
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def profile_path(system: Path, name: str) -> Path:
    """Return the role profile path inside the system directory."""
    return system / f"{name}.md"


def bootstrap(system: Path) -> None:
    """Create any missing role-profile files."""
    system.mkdir(parents=True, exist_ok=True)
    for name, description in PROFILE_DESCRIPTIONS.items():
        path = profile_path(system, name)
        if path.exists():
            continue
        text = (
            "---\n"
            f"description: {description}\n"
            "---\n"
            f"# {_PROFILE_TITLES[name]}\n\n"
            "## Guidance\n"
        )
        atomic_write(path, text)


def apply_proposal(system: Path, proposal: ProfileProposalView) -> None:
    """Apply one validated proposal to its role-profile file."""
    path = profile_path(system, proposal.profile)
    current = path.read_text(encoding="utf-8")
    lines = current.splitlines()
    old_line = f"- {proposal.old_text}" if proposal.old_text else ""
    new_line = f"- {proposal.content}" if proposal.content else ""

    match proposal.action:
        case "add":
            if new_line not in lines:
                atomic_write(path, f"{current.rstrip()}\n{new_line}\n")
            return
        case "replace":
            try:
                index = lines.index(old_line)
            except ValueError:
                return
            if new_line in lines:
                _ = lines.pop(index)
            else:
                lines[index] = new_line
        case "remove":
            try:
                lines.remove(old_line)
            except ValueError:
                return
        case unreachable:
            _assert_never(unreachable)
    atomic_write(path, "\n".join(lines).rstrip() + "\n")


def read_profiles(system: Path) -> dict[str, list[str]]:
    """Return persisted guidance for each role profile."""
    return {
        name: read_guidance(profile_path(system, name))
        for name in PROFILE_DESCRIPTIONS
    }


def read_guidance(path: Path) -> list[str]:
    """Read bullet guidance from one role-profile file."""
    text = path.read_text(encoding="utf-8")
    _, _, guidance = text.partition("## Guidance")
    return [
        line.removeprefix("- ").strip()
        for line in guidance.splitlines()
        if line.startswith("- ")
    ]
