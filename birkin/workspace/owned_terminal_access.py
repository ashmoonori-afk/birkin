"""Workspace and approval boundary for owned terminal creation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import final

from birkin import approvals, config, store
from birkin.config_model import Config

from .approval_projection import approval_item
from .contracts import ProtocolError, TerminalApprovalRequired
from .owned_terminal_session import TerminalEventSink

TERMINAL_SHELL = "/bin/sh"


@final
class TerminalAccessAuthority:
    """Resolve workspace paths and consume one-use shell approvals."""

    def __init__(
        self,
        session_id: str,
        workspace_root: Path,
        config_loader: Callable[[], Config],
    ) -> None:
        self._session_id = session_id
        self._workspace_root = workspace_root
        self._config_loader = config_loader

    def resolve_cwd(self, value: object) -> Path:
        if not isinstance(value, str):
            raise ProtocolError("terminal cwd must be a string")
        cwd = Path(value).expanduser().resolve()
        try:
            _ = cwd.relative_to(self._workspace_root)
        except ValueError as exc:
            raise ProtocolError("terminal cwd is outside the workspace") from exc
        if not cwd.is_dir():
            raise ProtocolError("terminal cwd does not exist")
        return cwd

    def authorize(
        self,
        cwd: Path,
        approval_id: object,
        emit: TerminalEventSink,
    ) -> str:
        if approval_id is None:
            proposal: dict[str, object] = approvals.propose(
                category="shell",
                title="Native terminal shell access",
                description="Allow a Python-owned interactive shell for the native human.",
                payload=self._approval_payload(cwd),
                cfg=self._config_loader(),
                origin="native_human",
            )
            approval_id = str(proposal["id"])
            if not proposal.get("auto"):
                pending = store.get_pending(approval_id)
                if pending is not None:
                    projected = approval_item(pending)
                    _ = emit(
                        "approval.requested",
                        {"approval_id": approval_id, **projected},
                    )
                raise TerminalApprovalRequired(approval_id)
        if not isinstance(approval_id, str) or not self._approved(
            approval_id,
            cwd=cwd,
        ):
            raise TerminalApprovalRequired(str(approval_id))
        return approval_id

    def _approved(self, approval_id: str, *, cwd: Path) -> bool:
        if not store.valid_pending_id(approval_id):
            return False
        approval_path = config.pending_dir() / f"{approval_id}.json"
        try:
            with store.file_lock(approval_path):
                record = store.get_pending(approval_id)
                if (
                    not isinstance(record, dict)
                    or record.get("status") != "approved"
                    or record.get("category") != "shell"
                    or record.get("payload") != self._approval_payload(cwd)
                ):
                    return False
                _ = store.resolve_pending(approval_id, "consumed")
        except store.FileLockTimeout:
            return False
        return True

    def _approval_payload(self, cwd: Path) -> dict[str, object]:
        return {
            "command": "/usr/bin/true",
            "shell": TERMINAL_SHELL,
            "cwd": str(cwd),
            "terminal_lease_only": True,
            "session_id": self._session_id,
            "actor_kind": "native_human",
        }
