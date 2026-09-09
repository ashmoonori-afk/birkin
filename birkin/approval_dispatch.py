"""Dispatch for actions that already crossed the canonical approval gate."""

from __future__ import annotations

import importlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from . import cron
from .approval_execution_codec import JSONValue
from .approval_execution_types import SealedApprovalId
from .operation_policy import retry_environment
from .proc import ShellCommand, run_shell_command, shell_env


@dataclass(frozen=True, slots=True)
class DispatchOptions:
    cfg: dict[str, Any] | None = None
    on_event: Any = None
    shell_runner: Any = run_shell_command
    office_approval_id: SealedApprovalId | None = None


@runtime_checkable
class _OperationExecutor(Protocol):
    def execute_approved(
        self, payload: dict[str, Any], cfg: dict[str, Any] | None
    ) -> str: ...


@runtime_checkable
class _ComputerUseExecutor(Protocol):
    def approve_payload(self, payload: dict[str, Any]) -> str: ...


@runtime_checkable
class _CheckpointExecutor(Protocol):
    def execute_approved_restore(self, payload: dict[str, Any]) -> str: ...


@runtime_checkable
class _MoiraiExecutor(Protocol):
    def run_approved(self, payload: dict[str, Any], on_event: Any = None) -> str: ...


@runtime_checkable
class _WorkerExecutor(Protocol):
    def execute_approved(self, payload: dict[str, JSONValue]) -> str: ...


@runtime_checkable
class _SkillExecutor(Protocol):
    def apply_skill_proposal(self, payload: dict[str, Any]) -> str: ...


@runtime_checkable
class _CompanionExecutor(Protocol):
    def apply_proposal(self, payload: dict[str, Any]) -> str: ...


@runtime_checkable
class _HarnessExecutor(Protocol):
    def apply_approved_edit(self, payload: dict[str, Any]) -> str: ...


def execute_action(
    category: str,
    payload: dict[str, Any],
    options: DispatchOptions | None = None,
) -> str:
    """Carry out an action that already has durable approval authority."""
    configured = options or DispatchOptions()
    if category == "cron":

        def clock(value: Any, default: int, maximum: int) -> int:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                parsed = default
            return max(0, min(maximum, parsed))

        schedule = payload.get("schedule")
        if schedule and cron.parse_schedule(str(schedule)) is None:
            schedule = None

        def optional_text(value: Any) -> str | None:
            text = str(value).strip() if value is not None else ""
            return text or None

        job = cron.add_job(
            name=payload.get("name", "job"),
            hour=clock(payload.get("hour", 9), 9, 23),
            minute=clock(payload.get("minute", 0), 0, 59),
            action_type=payload.get("type", "prompt"),
            value=payload.get("value", ""),
            deliver_chat_id=payload.get("deliver_chat_id"),
            deliver_channel=str(payload.get("deliver_channel") or "telegram"),
            schedule=str(schedule) if schedule else None,
            monitor_url=optional_text(payload.get("monitor_url")),
            monitor_script=optional_text(payload.get("monitor_script")),
            max_bytes=payload.get("max_bytes"),
        )
        return (
            f"Registered cron job '{job['name']}' at "
            f"{cron.schedule_display(job)} (id {job['id']})."
        )
    if category == "shell":
        if payload.get("terminal_lease_only") is True:
            required = {
                "command",
                "shell",
                "cwd",
                "terminal_lease_only",
                "session_id",
                "actor_kind",
            }
            raw_cwd = payload.get("cwd")
            session_id = payload.get("session_id")
            if (
                set(payload) != required
                or payload.get("command") != "/usr/bin/true"
                or payload.get("shell") != "/bin/sh"
                or payload.get("actor_kind") != "native_human"
                or not isinstance(raw_cwd, str)
                or not isinstance(session_id, str)
                or not session_id
                or not Path(raw_cwd).expanduser().resolve().is_dir()
            ):
                raise ValueError("invalid terminal lease approval payload")
            return "Approved native terminal lease."
        command = str(payload.get("command") or "")
        if not command:
            return "No command to run."
        cwd = Path(str(payload.get("cwd") or Path.cwd())).expanduser().resolve()
        if not cwd.is_dir():
            return f"Working directory does not exist: {cwd}"
        environment = shell_env()
        command_name = (
            command.strip()
            .split(maxsplit=1)[0]
            .strip("\"'")
            .replace("\\", "/")
            .rsplit("/", 1)[-1]
            .casefold()
            .removesuffix(".exe")
            .removesuffix(".cmd")
        )
        if command_name in {"bun", "bunx"}:
            local_temp = retry_environment("local_temp_policy", cwd)
            for key in ("TEMP", "TMP", "UV_CACHE_DIR"):
                Path(local_temp[key]).mkdir(parents=True, exist_ok=True)
            environment.update(local_temp)
        try:
            timeout = payload.get("timeout", 300)
            try:
                timeout = int(timeout)
            except (TypeError, ValueError):
                timeout = 300
            result = configured.shell_runner(
                ShellCommand(
                    command=command,
                    cwd=cwd,
                    timeout=max(1, min(3600, timeout)),
                    environment=environment,
                    hide_window=True,
                )
            )
        except subprocess.TimeoutExpired:
            return "Command timed out."
        output = (result.stdout or "") + (result.stderr or "")
        return f"[exit {result.returncode}] {output[:2000]}"
    if category == "office_create":
        approval_id = configured.office_approval_id
        if approval_id is None and configured.cfg is not None:
            value = configured.cfg.get("_office_approval_id")
            if isinstance(value, str):
                approval_id = SealedApprovalId(value)
        from .office.create_execution import execute_approved_office_creation

        return execute_approved_office_creation(
            payload,
            approval_id=approval_id,
        )
    if category == "office_job":
        approval_id = configured.office_approval_id
        if approval_id is None and configured.cfg is not None:
            value = configured.cfg.get("_office_approval_id")
            if isinstance(value, str):
                approval_id = SealedApprovalId(value)
        from .office.coordinator import execute_approved_office_job
        from .office.progress import office_progress_sink

        return execute_approved_office_job(
            payload,
            approval_id=approval_id,
            on_transition=office_progress_sink(configured.on_event),
        )
    if category == "office_rollback":
        from .office.rollback_approval import execute_approved_rollback

        approval_id = configured.office_approval_id
        if approval_id is None and configured.cfg is not None:
            value = configured.cfg.get("_office_approval_id")
            if isinstance(value, str):
                approval_id = SealedApprovalId(value)
        return execute_approved_rollback(payload, approval_id=approval_id)
    if category == "office_batch":
        from .office.batch import execute

        return execute(payload, approval_id=configured.office_approval_id, on_transition=configured.on_event)
    if category == "work_item":
        from .work_items import apply_approved

        return apply_approved(payload, configured.on_event)
    if category == "connection":
        from .m365_connection import apply_approved

        return apply_approved(payload, configured.on_event)
    if category == "mail_send":
        from .m365_mail import execute_approved_send

        return execute_approved_send(payload)
    if category == "calendar_event":
        from .m365_calendar import execute_approved_event

        return execute_approved_event(payload)
    if category == "briefing_schedule":
        from .daily_briefing import apply_schedule

        return apply_schedule(payload, configured.on_event)
    if category == "team_share":
        from .team_review import execute_share

        return execute_share(payload, approval_id=configured.office_approval_id)
    if category == "office_template":
        from .office.saved_templates import apply_approved

        return apply_approved(payload)
    if category == "data_delete":
        from .data_controls import delete_work_copy

        return delete_work_copy(payload)
    if category == "operation":
        operation = importlib.import_module("birkin.operation_approval")
        if not isinstance(operation, _OperationExecutor):
            raise RuntimeError("operation approval executor is unavailable")
        return operation.execute_approved(payload, configured.cfg)
    if category == "computer_use":
        computer_use = importlib.import_module("birkin.computer_use.approval_bridge")
        if not isinstance(computer_use, _ComputerUseExecutor):
            raise RuntimeError("Computer Use approval executor is unavailable")
        return computer_use.approve_payload(payload)
    if category == "checkpoint_restore":
        checkpoint_executor = importlib.import_module("birkin.checkpoints")
        if not isinstance(checkpoint_executor, _CheckpointExecutor):
            raise RuntimeError("checkpoint approval executor is unavailable")
        return checkpoint_executor.execute_approved_restore(payload)
    if category == "moirai":
        moirai = importlib.import_module("birkin.moirai.trigger")
        if not isinstance(moirai, _MoiraiExecutor):
            raise RuntimeError("Moirai approval executor is unavailable")
        return moirai.run_approved(payload, on_event=configured.on_event)
    if category == "worker":
        worker = importlib.import_module("birkin.worker_executor")
        if not isinstance(worker, _WorkerExecutor):
            raise RuntimeError("worker approval executor is unavailable")
        return worker.execute_approved(payload)
    if category == "skill":
        skill = importlib.import_module("birkin.skills.manager")
        if not isinstance(skill, _SkillExecutor):
            raise RuntimeError("skill approval executor is unavailable")
        return skill.apply_skill_proposal(payload)
    if category == "companion":
        companion = importlib.import_module("birkin.companion")
        if not isinstance(companion, _CompanionExecutor):
            raise RuntimeError("companion approval executor is unavailable")
        return companion.apply_proposal(payload)
    if category == "harness":
        harness = importlib.import_module("birkin.harness")
        if not isinstance(harness, _HarnessExecutor):
            raise RuntimeError("harness approval executor is unavailable")
        return harness.apply_approved_edit(payload)
    if category == "memory":
        return "(memory is applied directly by the agent)"
    raise ValueError(f"unknown approval category {category!r}")
