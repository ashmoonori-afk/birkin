"""Trusted write boundary and durable approval queue for role profiles."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Literal, Sequence

from .rolefiles import (
    PROFILE_ORDER,
    ProfileBudgetExceeded,
    ProfileEdit,
    ProfileRevisionError,
    ProfileStore,
)
from .tools import Tool, ToolContext, ToolResult

Status = Literal["applied", "pending", "rejected", "error"]

_BIDI = {"RLO", "LRO", "RLE", "LRE", "PDF", "RLI", "LRI", "FSI", "PDI"}
# Best-effort rejects for common credential shapes; not a secret-scanning guarantee.
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*\S{8,}", re.I),
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b"),
    re.compile(r"\b[A-Za-z0-9+/]{32,}={0,2}\b"),
)

@dataclass(frozen=True)
class ProfileReceipt:
    """Machine-readable result for a submitted profile edit."""

    id: str
    status: Status
    edit: ProfileEdit
    source: str
    revision: str = ""
    error: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        if self.error is None:
            data.pop("error")
        return data


class ProfileValidationError(ValueError):
    """Rejected profile content at Birkin's trust boundary."""


def validate_profile_text(text: str) -> str:
    """Normalize and reject content unsafe for role-profile markdown."""
    value = " ".join(str(text).split())
    if not value:
        return ""
    for ch in value:
        code = ord(ch)
        cat = unicodedata.category(ch)
        bidi = unicodedata.bidirectional(ch)
        if ch == "\x00" or (cat == "Cc" and ch not in "\t\n\r"):
            raise ProfileValidationError("control character in profile content")
        if cat in {"Cf", "Cs", "Co", "Cn"} or bidi in _BIDI:
            raise ProfileValidationError("invisible or bidi unicode in profile content")
        if code in {0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF}:
            raise ProfileValidationError("invisible unicode in profile content")
    if value.startswith(("---", "```")) or "\n---" in value or "\n```" in value:
        raise ProfileValidationError("markdown boundary marker in profile content")
    if value.startswith(('#', '<!--')) or "</system" in value.lower():
        raise ProfileValidationError("markdown boundary breakage in profile content")
    for pattern in _SECRET_PATTERNS:
        if pattern.search(value):
            raise ProfileValidationError("credential-shaped text in profile content")
    return value


def _budget_payload(exc: ProfileBudgetExceeded) -> dict[str, Any]:
    return {
        "type": "budget_exceeded",
        "used": exc.used,
        "limit": exc.limit,
        "required_reduction": exc.required_reduction,
        "revision": exc.revision,
        "entries": list(exc.entries),
    }


def _normalize_edit(edit: ProfileEdit) -> ProfileEdit:
    return ProfileEdit(
        target=edit.target,
        action=edit.action,
        old_text=validate_profile_text(edit.old_text),
        content=validate_profile_text(edit.content),
    )


class ProfileActions:
    """Single write path for foreground tools and background review proposals."""

    def __init__(self, store: ProfileStore, *, approval_required: bool) -> None:
        self.store = store
        self.approval_required = bool(approval_required)
        self.store.bootstrap()
        self._path = self.store.root / "pending-v1.json"

    def submit(self, edit: ProfileEdit, *, trusted: bool, source: str) -> ProfileReceipt:
        if not trusted:
            return ProfileReceipt(
                id="", status="error", edit=edit, source=source,
                error={"type": "untrusted"},
            )
        try:
            clean = _normalize_edit(edit)
            revision = self.store.snapshot().revision
            if self.approval_required:
                receipt = ProfileReceipt(
                    id=uuid.uuid4().hex, status="pending", edit=clean,
                    source=source, revision=revision,
                )
                self._append(receipt)
                return receipt
            snapshot = self.store.apply(clean, expected_revision=revision)
            return ProfileReceipt(
                id=uuid.uuid4().hex, status="applied", edit=clean,
                source=source, revision=snapshot.revision,
            )
        except ProfileBudgetExceeded as exc:
            return ProfileReceipt("", "error", edit, source, error=_budget_payload(exc))
        except (ProfileValidationError, ValueError) as exc:
            return ProfileReceipt("", "error", edit, source, error={"type": "invalid", "message": str(exc)})
        except ProfileRevisionError as exc:
            return ProfileReceipt("", "error", edit, source, error={"type": "stale_revision", "message": str(exc)})

    def pending(self) -> tuple[ProfileReceipt, ...]:
        return tuple(self._load())

    def approve(self, ids: Sequence[str]) -> tuple[ProfileReceipt, ...]:
        want = set(ids)
        kept: list[ProfileReceipt] = []
        out: list[ProfileReceipt] = []
        for receipt in self._load():
            if receipt.id not in want:
                kept.append(receipt)
                continue
            try:
                clean = _normalize_edit(receipt.edit)
                snapshot = self.store.apply(clean, expected_revision=receipt.revision)
                out.append(ProfileReceipt(receipt.id, "applied", clean, receipt.source, snapshot.revision))
            except ProfileBudgetExceeded as exc:
                kept.append(receipt)
                out.append(ProfileReceipt(receipt.id, "error", receipt.edit, receipt.source, receipt.revision, _budget_payload(exc)))
            except ProfileRevisionError as exc:
                kept.append(receipt)
                out.append(ProfileReceipt(receipt.id, "error", receipt.edit, receipt.source, receipt.revision, {"type": "stale_revision", "message": str(exc)}))
            except (ProfileValidationError, ValueError) as exc:
                kept.append(receipt)
                out.append(ProfileReceipt(receipt.id, "error", receipt.edit, receipt.source, receipt.revision, {"type": "invalid", "message": str(exc)}))
        self._save(kept)
        return tuple(out)

    def reject(self, ids: Sequence[str]) -> tuple[ProfileReceipt, ...]:
        want = set(ids)
        kept: list[ProfileReceipt] = []
        out: list[ProfileReceipt] = []
        for receipt in self._load():
            if receipt.id in want:
                out.append(ProfileReceipt(receipt.id, "rejected", receipt.edit, receipt.source, receipt.revision))
            else:
                kept.append(receipt)
        self._save(kept)
        return tuple(out)

    def _append(self, receipt: ProfileReceipt) -> None:
        items = list(self._load())
        items.append(receipt)
        self._save(items)

    def _load(self) -> list[ProfileReceipt]:
        if not self._path.exists():
            return []
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        items = raw.get("pending", []) if isinstance(raw, dict) else []
        out: list[ProfileReceipt] = []
        for item in items:
            edit = ProfileEdit(**item["edit"])
            out.append(ProfileReceipt(
                id=str(item["id"]), status="pending", edit=edit,
                source=str(item.get("source", "")),
                revision=str(item.get("revision", "")),
            ))
        return out

    def _save(self, items: Sequence[ProfileReceipt]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(self._path.parent, 0o700)
        # Windows ACLs are not set here; os.chmod only exposes a read-only bit.
        payload = {"version": 1, "pending": [item.payload() for item in items]}
        fd, tmp = tempfile.mkstemp(prefix=".pending-v1.", dir=str(self._path.parent))
        if os.name == "posix":
            os.fchmod(fd, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(tmp, self._path)
            if os.name == "posix":
                os.chmod(self._path, 0o600)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

def build_profile_tools(actions: ProfileActions) -> list[Any]:
    """Build the foreground profile_write tool."""

    def profile_write(inp: dict[str, Any], _ctx: ToolContext) -> ToolResult:
        raw_action = str(inp.get("action", ""))
        match raw_action:
            case "add" | "replace" | "remove":
                action = raw_action
            case _:
                payload = {
                    "error": {
                        "type": "invalid",
                        "message": f"unknown profile action: {raw_action}",
                    },
                    "source": "tool",
                    "status": "error",
                }
                return ToolResult(json.dumps(payload, sort_keys=True), True)
        edit = ProfileEdit(
            target=str(inp.get("target", "")),
            action=action,
            old_text=str(inp.get("old_text", "")),
            content=str(inp.get("content", "")),
        )
        receipt = actions.submit(edit, trusted=True, source="tool")
        return ToolResult(json.dumps(receipt.payload(), sort_keys=True), receipt.status == "error")

    return [Tool(
        name="profile_write",
        description="Write trusted role-profile guidance. Use add, replace, or remove.",
        input_schema={"type": "object", "properties": {
            "target": {"type": "string", "enum": list(PROFILE_ORDER)},
            "action": {"type": "string", "enum": ["add", "replace", "remove"]},
            "old_text": {"type": "string"},
            "content": {"type": "string"},
        }, "required": ["target", "action"]},
        fn=profile_write,
    )]
