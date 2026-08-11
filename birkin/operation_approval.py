"""Digest-bound, one-shot approvals for retriable native tool operations."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .operation_policy import (
    ApprovalRequiredError,
    retry_environment,
)

if TYPE_CHECKING:
    from .tools import ToolContext, ToolResult
    from .tools._types import Config, ToolInput


_REPLAYABLE_TOOLS = frozenset({
    "read_file",
    "edit_file",
    "write_file",
    "list_files",
    "run_shell",
    "web_fetch",
    "web_search",
    "market_quote",
    "verify_citations",
    "session_search",
    "session_get",
    "submit_payload",
})
_REPLAY_GROUPS = {
    "files",
    "shell",
    "web",
    "sessions",
    "egress",
}
@dataclass(frozen=True, slots=True)
class OperationApprovalError(RuntimeError):
    """A digest-bound operation is invalid or its approved replay failed."""

    detail: str

    def __str__(self) -> str:
        return self.detail


def queue_operation(
    tool: str,
    tool_input: ToolInput,
    ctx: ToolContext,
    block: ApprovalRequiredError,
) -> ToolResult:
    """Queue the exact failed operation for mandatory manual review."""
    from . import approvals, store
    from .tools import ToolResult

    if "_approved_env" in tool_input:
        return ToolResult(
            "Tool input contains reserved approval executor metadata",
            is_error=True,
        )
    if ctx.approved_operation:
        return ToolResult(
            f"Approved operation failed at {block.gate}: {block.detail}",
            is_error=True,
        )
    if tool not in _REPLAYABLE_TOOLS:
        return ToolResult(
            f"Tool '{tool}' blocked at {block.gate}: {block.detail}. "
            "This context-bound tool uses its dedicated approval flow.",
            is_error=True,
        )

    cwd = ctx.cwd.resolve()
    operation = {
        "version": 1,
        "tool": tool,
        "input": tool_input,
        "cwd": str(cwd),
        "gate": block.gate,
    }
    environment = retry_environment(block.gate, cwd)
    if environment:
        operation["environment"] = environment
    try:
        canonical = _canonical(operation)
    except (TypeError, ValueError) as exc:
        return ToolResult(
            f"Tool '{tool}' blocked, but its input could not be bound: {exc}",
            is_error=True,
        )
    digest = hashlib.sha256(canonical).hexdigest()
    for pending in store.list_pending():
        if (
            pending.get("category") == "operation"
            and pending.get("payload", {}).get("digest") == digest
        ):
            return ToolResult(
                f"Approval required: {block.detail}; retry already queued "
                f"for approval (id {pending['id']}, gate {block.gate}).",
                is_error=True,
            )
    record = approvals.propose(
        category="operation",
        title=f"Retry blocked {tool} operation",
        description=f"{block.detail}. Approve one exact retry.",
        payload={"operation": operation, "digest": digest},
        origin="native_tool",
        cfg=ctx.cfg,
    )
    return ToolResult(
        f"Approval required: {block.detail}; retry queued for approval "
        f"(id {record['id']}, gate {block.gate}).",
        is_error=True,
    )


def execute_approved(payload: ToolInput, cfg: Config | None) -> str:
    """Verify and replay one digest-bound native operation."""
    from . import checkpoints, hooks
    from .tools import ToolContext, build_registry

    if cfg is None:
        from . import config
        cfg = config.load_config()

    operation_value = payload.get("operation")
    digest = payload.get("digest")
    if not isinstance(operation_value, dict) or not isinstance(digest, str):
        raise OperationApprovalError("Invalid approval operation payload")
    operation = cast("ToolInput", operation_value)
    if operation.get("version") != 1:
        raise OperationApprovalError("Unsupported operation approval version")
    if not hmac.compare_digest(
        hashlib.sha256(_canonical(operation)).hexdigest(),
        digest,
    ):
        raise OperationApprovalError("Operation approval digest mismatch")

    tool = operation.get("tool")
    tool_input_value = operation.get("input")
    cwd_value = operation.get("cwd")
    if tool not in _REPLAYABLE_TOOLS:
        raise OperationApprovalError(f"Tool is not replayable: {tool}")
    if not isinstance(tool_input_value, dict) or not isinstance(cwd_value, str):
        raise OperationApprovalError("Invalid approval operation fields")
    tool_input = cast("ToolInput", tool_input_value)
    cwd = Path(cwd_value)
    if not cwd.is_absolute():
        raise OperationApprovalError(
            "Approved operation cwd must be absolute",
        )
    environment_value = operation.get("environment")
    environment: dict[str, str] = {}
    if environment_value is not None:
        if not isinstance(environment_value, dict):
            raise OperationApprovalError(
                "Invalid approved operation environment",
            )
        for key, value in environment_value.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise OperationApprovalError(
                    "Invalid approved operation environment",
                )
            environment[key] = value
    effective_input = dict(tool_input)
    effective_input.pop("_approved_env", None)
    if environment:
        effective_input["_approved_env"] = environment

    ctx = ToolContext(
        cfg=cfg,
        client=None,
        cwd=cwd,
        approved_operation=True,
        checkpoints=checkpoints.CheckpointManager(
            enabled=bool(cfg.get("checkpoints", True)),
            keep=int(cfg.get("checkpoint_keep", 20)),
        ),
        hooks=hooks.build_bus(cfg),
    )
    registry = build_registry(
        ctx,
        include=_REPLAY_GROUPS,
        approval_replay=True,
    )
    result = registry.execute(tool, effective_input)
    if result.is_error:
        raise OperationApprovalError(result.content)
    return result.content


def _canonical(operation: ToolInput) -> bytes:
    return json.dumps(
        operation,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
