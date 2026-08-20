"""Human-in-the-loop approval gate for consequential actions.

Policy (configurable via the REPL ``/permission`` command):
- Categories in ``config["auto_approve"]`` (default ``memory``, ``skill``) are
  applied immediately. The name must match :func:`is_auto`'s exact membership
  test — ``skill``, not ``skills``. A plural that matches nothing looks
  configured and behaves as if it were not, so :func:`security.gateway_warnings`
  flags any category it does not recognise.
- Everything else (e.g. ``cron``, ``shell``) is queued in
  ``~/.birkin/pending/`` and only executes after the user approves it with
  ``birkin review`` or the dashboard.

The agent and the Morpheus routine call :func:`propose`; they never execute
consequential actions directly.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import actions, config, cron, risk, store, worker_hooks
from .operation_policy import retry_environment
from .proc import ShellCommand, run_shell_command, shell_env


def is_auto(category: str, cfg: dict[str, Any]) -> bool:
    return category in (cfg.get("auto_approve") or [])


def worker_hook_contract() -> dict[str, Any]:
    return worker_hooks.contract()


def _is_shell_cron(category: str, payload: dict[str, Any]) -> bool:
    """A cron job whose payload runs a shell command — as dangerous as `shell`.

    Two payload shapes qualify. The ``type`` is normalised (case/whitespace) so
    a capitalised ``"Shell"`` can't slip a shell payload past this gate. A
    ``monitor`` job carrying ``monitor_script`` also runs that command through
    the shell — unattended, on every tick — so it is gated identically instead
    of riding on a "schedule things for me" policy.
    """
    if category != "cron":
        return False
    payload = payload or {}
    if str(payload.get("type", "")).strip().lower() == "shell":
        return True
    return bool(str(payload.get("monitor_script") or "").strip())


def propose(*, category: str, title: str, description: str,
            payload: dict[str, Any], cfg: dict[str, Any],
            origin: str = "morpheus",
            continuation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply (if auto-approved) or queue an action. Returns a status dict.

    SECURITY: an auto-approved ``cron`` must not launder a *shell* payload past
    the (separate) ``shell`` gate — otherwise a trusted "schedule things" policy
    silently grants unattended arbitrary code execution. A shell-typed cron job
    is only auto-applied when ``shell`` itself is auto-approved; otherwise it is
    queued for explicit human review regardless of the ``cron`` policy.
    """
    parsed_continuation = (
        worker_hooks.validate(continuation) if continuation is not None else None
    )
    auto = (
        category != "operation"
        and continuation is None
        and is_auto(category, cfg)
        and not (
        _is_shell_cron(category, payload) and not is_auto("shell", cfg))
    )
    rec = store.add_pending(category=category, title=title,
                            description=description, payload=payload,
                            origin=origin,
                            continuation=parsed_continuation)
    if auto:
        resolved = approve(rec["id"])
        return {"auto": True, "ok": bool(resolved.get("ok")),
                "id": rec["id"], "category": category,
                "result": resolved.get("result", resolved.get("error", ""))}
    return {"auto": False, "id": rec["id"], "title": title}


def request_answers(
    *,
    title: str,
    description: str,
    questions: list[dict[str, Any]],
    origin: str,
    timeout_seconds: int = 300,
    allow_clarification: bool = True,
) -> dict[str, Any]:
    """Persist a channel-neutral action that needs structured answers."""
    normalized = actions.normalize_questions(questions)
    timeout = max(1, min(86_400, int(timeout_seconds)))
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=timeout)
    ).isoformat(timespec="seconds")
    record = store.add_pending(
        category="question",
        title=title,
        description=description,
        payload={},
        origin=origin,
        details={
            "action_state": "action_needed",
            "questions": normalized,
            "allow_clarification": bool(allow_clarification),
            "expires_at": expires_at,
        },
    )
    return {
        "ok": True,
        "event": "action_needed",
        "id": record["id"],
        "questions": normalized,
        "expires_at": expires_at,
    }


def _is_moirai_continuation(aid: str) -> bool:
    """Claim the action for the durable contract before the journal is read.

    The pending projection is the only trust anchor left when the journal row
    is missing or unreadable; without this the plain answer path would resolve
    a Moirai checkpoint with none of its binding checks.
    """
    record = store.get_pending(aid)
    envelope = (record or {}).get("continuation")
    return (
        isinstance(envelope, dict)
        and envelope.get("handler") == "moirai.resume.v1"
    )


def answer(
    aid: str,
    *,
    answers: dict[str, Any],
    source: str,
    clarification: str = "",
    navigation: list[str] | None = None,
    capability: str = "",
    resume_token: str = "",
    question_digest: str = "",
    input_schema_version: int | None = None,
    previous_state_digest: str = "",
) -> dict[str, Any]:
    """Resolve one structured action with a validated answer set."""
    from .moirai import continuation, journal

    if _is_moirai_continuation(aid) or journal.get_input_wait(aid) is not None:
        return continuation.accept(
            aid,
            answers=answers,
            actor=source,
            capability=capability,
            resume_token=resume_token,
            question_digest=question_digest,
            input_schema_version=input_schema_version,
            previous_state_digest=previous_state_digest,
            clarification=clarification,
            navigation=navigation,
        )
    try:
        with store.file_lock(_pending_path(aid)):
            record = store.get_pending(aid)
            if (not record or record.get("status") != "pending"
                    or record.get("action_state") != "action_needed"):
                return {"ok": False, "event": "reply_rejected", "id": aid,
                        "error": "not found or already resolved"}

            expires_at = datetime.fromisoformat(str(record["expires_at"]))
            if expires_at.tzinfo is None:
                raise ValueError("invalid action expiry")
            if expires_at <= datetime.now(timezone.utc):
                store.resolve_pending(
                    aid,
                    "expired",
                    details={"action_state": "action_expired"},
                )
                return {"ok": False, "event": "reply_rejected", "id": aid,
                        "error": "action expired"}

            normalized = actions.normalize_answers(
                record.get("questions") or [], answers)
            details: dict[str, Any] = {
                "action_state": "action_resolved",
                "answers": normalized,
                "resolved_by": source,
            }
            if clarification and record.get("allow_clarification"):
                details["clarification"] = clarification[:2_000]
            if navigation:
                details["navigation"] = [
                    str(item)[:64] for item in navigation[-50:]]
            store.resolve_pending(aid, "answered", details=details)
    except (actions.InvalidAnswer, KeyError, ValueError) as exc:
        return {"ok": False, "event": "reply_rejected", "id": aid,
                "error": str(exc)}
    except store.FileLockTimeout:
        return {"ok": False, "event": "reply_rejected", "id": aid,
                "error": "action is busy; retry"}
    return {
        "ok": True,
        "event": "action_resolved",
        "id": aid,
        "answers": normalized,
        "resolved_by": source,
    }


def execute_action(category: str, payload: dict[str, Any],
                   cfg: dict[str, Any] | None = None,
                   on_event: Any = None) -> str:
    """Carry out an approved action. Returns a human-readable result.

    ``cfg`` is accepted for policy-aware callers (see :func:`propose`); manual
    approval via :func:`approve` has already gathered explicit human consent.
    """
    if category == "cron":
        def _clk(v: Any, d: int, hi: int) -> int:
            # A model/user payload may carry a non-int (e.g. "9; rm") or an
            # out-of-range value (e.g. 25): default on garbage, clamp to 0..hi
            # so we never raise mid-execution or store a time that can't fire.
            try:
                n = int(v)
            except (TypeError, ValueError):
                n = d
            return max(0, min(hi, n))
        # A proposal may carry a schedule expression ("every 30m", "0 9 * * 1")
        # or the original hour/minute pair. An unparseable expression falls
        # back to hour/minute rather than failing the approved action.
        schedule = payload.get("schedule")
        if schedule and cron.parse_schedule(str(schedule)) is None:
            schedule = None
        def _opt_text(value: Any) -> str | None:
            text = str(value).strip() if value is not None else ""
            return text or None

        # Monitor sources travel with the proposal: dropping them here produced
        # an approved job whose every tick failed for want of a source.
        job = cron.add_job(
            name=payload.get("name", "job"),
            hour=_clk(payload.get("hour", 9), 9, 23),
            minute=_clk(payload.get("minute", 0), 0, 59),
            action_type=payload.get("type", "prompt"),
            value=payload.get("value", ""),
            deliver_chat_id=payload.get("deliver_chat_id"),
            deliver_channel=str(
                payload.get("deliver_channel") or "telegram"
            ),
            schedule=str(schedule) if schedule else None,
            monitor_url=_opt_text(payload.get("monitor_url")),
            monitor_script=_opt_text(payload.get("monitor_script")),
            max_bytes=payload.get("max_bytes"))
        return f"Registered cron job '{job['name']}' at " \
               f"{cron.schedule_display(job)} (id {job['id']})."
    if category == "shell":
        command = str(payload.get("command") or "")
        if not command:
            return "No command to run."
        if payload.get("terminal_lease_only") is True:
            return "Terminal shell access approved; no command executed."
        cwd = Path(str(payload.get("cwd") or Path.cwd())).expanduser().resolve()
        if not cwd.is_dir():
            return f"Working directory does not exist: {cwd}"
        environment = shell_env()
        command_name = command.strip().split(maxsplit=1)[0] \
            .strip("\"'").replace("\\", "/").rsplit("/", 1)[-1] \
            .casefold().removesuffix(".exe").removesuffix(".cmd")
        if command_name in {"bun", "bunx"}:
            local_temp = retry_environment("local_temp_policy", cwd)
            for key in ("TEMP", "TMP", "UV_CACHE_DIR"):
                Path(local_temp[key]).mkdir(parents=True, exist_ok=True)
            environment.update(local_temp)
        try:
            to = payload.get("timeout", 300)
            try:                           # model/user payload may be non-int
                to = int(to)
            except (TypeError, ValueError):
                to = 300
            proc = run_shell_command(
                ShellCommand(
                    command=command,
                    cwd=cwd,
                    timeout=max(1, min(3600, to)),
                    environment=environment,
                    hide_window=True,
                )
            )
        except subprocess.TimeoutExpired:
            return "Command timed out."
        out = (proc.stdout or "") + (proc.stderr or "")
        return f"[exit {proc.returncode}] {out[:2000]}"
    if category == "operation":
        from .operation_approval import execute_approved
        return execute_approved(payload, cfg)
    if category == "computer_use":
        from .computer_use.approval_bridge import approve_payload
        return approve_payload(payload)
    if category == "checkpoint_restore":
        from . import checkpoint_state
        from .checkpoints import CheckpointManager, RestoreMode
        workspace = Path(str(payload.get("workspace") or "")).expanduser().resolve()
        checkpoint = str(payload.get("checkpoint") or "")
        try:
            mode = RestoreMode(str(payload.get("mode") or ""))
        except ValueError as exc:
            raise ValueError("invalid checkpoint restore mode") from exc
        session_id = str(payload.get("session_id") or "")
        if mode is not RestoreMode.FILES and not session_id:
            raise ValueError("checkpoint restore requires a session id")
        manager = (
            CheckpointManager(enabled=True)
            if mode is RestoreMode.FILES
            else CheckpointManager(
                enabled=True,
                state_snapshot=lambda: checkpoint_state.snapshot(session_id),
                state_restore=lambda state: checkpoint_state.restore(
                    session_id,
                    state,
                ),
            )
        )
        outcome = manager.restore(workspace, checkpoint, mode=mode)
        if not outcome.ok:
            raise ValueError(outcome.message)
        return outcome.message
    if category == "moirai":
        from .moirai.trigger import run_approved
        return run_approved(payload, on_event=on_event)
    if category == "skill":
        from .skills.manager import apply_skill_proposal
        return apply_skill_proposal(payload)
    if category == "companion":
        from .companion import apply_proposal
        return apply_proposal(payload)
    if category == "harness":
        from .harness import apply_approved_edit
        return apply_approved_edit(payload)
    if category == "memory":
        return "(memory is applied directly by the agent)"
    raise ValueError(f"unknown approval category {category!r}")


# -- CLI review ------------------------------------------------------------

def _pending_path(aid: str):
    return config.pending_dir() / f"{aid}.json"


def reviewable_pending() -> list[dict[str, Any]]:
    return [rec for rec in store.list_pending()
            if rec.get("category") != "workflow"]


def claim(aid: str) -> dict[str, Any]:
    if not store.valid_pending_id(aid):
        return {"ok": False, "error": "invalid approval id"}
    # CLAIM under the lock (fast: read + status write), then EXECUTE outside it.
    # The claim — flipping status away from "pending" — is the gate against a
    # double-run (same item tapped in Telegram while also approved in the CLI).
    # Running the action (a shell job can be minutes) INSIDE the lock was the
    # bug: file_lock proceeds after a 5s timeout / reclaims a 30s-stale lock,
    # so a long approve could release the gate and let a second run start.
    try:
        with store.file_lock(_pending_path(aid)):
            rec = store.get_pending(aid)
            if not rec or rec.get("status") != "pending":
                return {"ok": False, "error": "not found or already resolved"}
            if rec.get("action_state") == "action_needed":
                return {
                    "ok": False,
                    "error": "structured action requires answers",
                }
            if rec.get("category") == "workflow":
                return {"ok": False,
                        "error": "Telegram workflow requires its origin chat"}
            store.resolve_pending(aid, "approving")     # claim it
    except store.FileLockTimeout:
        return {"ok": False, "error": "approval store is busy"}
    return {"ok": True}


def execute_claimed(aid: str, on_event: Any = None) -> dict[str, Any]:
    if not store.valid_pending_id(aid):
        return {"ok": False, "error": "invalid approval id"}
    try:
        with store.file_lock(_pending_path(aid)):
            rec = store.get_pending(aid)
            if not rec or rec.get("status") != "approving":
                return {"ok": False, "error": "approval is not claimed"}
            continuation = rec.get("continuation")
            if continuation is not None:
                try:
                    worker_hooks.validate(continuation)
                except worker_hooks.WorkerHookError as exc:
                    store.resolve_pending(
                        aid, "error",
                        updates={"failure_stage": "validation"},
                    )
                    return {"ok": False, "error": str(exc)}
            store.resolve_pending(aid, "executing")
    except store.FileLockTimeout:
        return {"ok": False, "error": "approval store is busy"}
    try:
        # The bare two-argument call is the contract tests (and any older
        # caller) replace execute_action through -- a surprise keyword on a
        # monkeypatched fake TypeErrors and reads as ok: False. Forward the
        # observer only when there is one.
        if on_event is not None:
            result = execute_action(rec["category"], rec.get("payload", {}),
                                    on_event=on_event)
        else:
            result = execute_action(rec["category"], rec.get("payload", {}))
    except store.FileLockTimeout:
        try:
            with store.file_lock(_pending_path(aid)):
                current = store.get_pending(aid)
                if not current or current.get("status") != "executing":
                    return {"ok": False, "error": "approval store is busy"}
                store.resolve_pending(aid, "pending")
        except store.FileLockTimeout:
            return {"ok": False, "error": "approval store is busy"}
        return {"ok": False, "error": "cron store is busy; retry."}
    except Exception as exc:
        store.resolve_pending(
            aid, "error", updates={"failure_stage": "action"},
        )
        return {"ok": False, "error": f"action failed: {exc}"}
    if continuation is not None:
        store.resolve_pending(
            aid, "resume_pending", updates={"action_receipt": result},
        )
        resumed = execute_continuation(aid, on_event=on_event)
        if resumed.get("ok"):
            resumed["result"] = result
        return resumed
    store.resolve_pending(aid, "approved", updates={"action_receipt": result})
    return {"ok": True, "result": result}


def execute_continuation(aid: str, on_event: Any = None) -> dict[str, Any]:
    if not store.valid_pending_id(aid):
        return {"ok": False, "error": "invalid approval id"}
    try:
        with store.file_lock(_pending_path(aid)):
            rec = store.get_pending(aid)
            if not rec or rec.get("status") != "resume_pending":
                return {"ok": False, "error": "continuation is not pending"}
            continuation = worker_hooks.validate(rec.get("continuation"))
            store.resolve_pending(aid, "resuming")
    except (store.FileLockTimeout, worker_hooks.WorkerHookError) as exc:
        return {"ok": False, "error": str(exc)}
    try:
        result = worker_hooks.dispatch(continuation, on_event=on_event)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        store.resolve_pending(
            aid, "error", updates={"failure_stage": "continuation"},
        )
        return {"ok": False, "error": f"continuation failed: {exc}"}
    store.resolve_pending(
        aid, "approved", updates={"continuation_result": result},
    )
    return {"ok": True, "continuation_result": result}


def restore_claim(aid: str) -> bool:
    if not store.valid_pending_id(aid):
        return False
    try:
        with store.file_lock(_pending_path(aid)):
            rec = store.get_pending(aid)
            if not rec or rec.get("status") != "approving":
                return False
            store.resolve_pending(aid, "pending")
    except store.FileLockTimeout:
        return False
    return True


def approve(aid: str, on_event: Any = None) -> dict[str, Any]:
    claimed = claim(aid)
    if not claimed.get("ok"):
        return claimed
    return execute_claimed(aid, on_event=on_event)


def reject(aid: str, reason: str = "") -> dict[str, Any]:
    if not store.valid_pending_id(aid):
        return {"ok": False}
    try:
        with store.file_lock(_pending_path(aid)):
            rec = store.get_pending(aid)
            if not rec or rec.get("status") != "pending":
                return {"ok": False}      # already resolved — don't clobber
            store.resolve_pending(aid, "rejected", reason=reason)
    except store.FileLockTimeout:
        return {"ok": False}
    return {"ok": True}


def denial_reason_for(command: str) -> str:
    """Why the user last refused this exact command, if they said.

    A denial with no reason leaves the model guessing: it either retries a
    variant blind or gives up. Feeding the reason back is what makes the
    approval loop converge instead of just stopping.
    """
    want = (command or "").strip()
    if not want:
        return ""
    newest, when = "", ""
    for rec in store.list_resolved("rejected"):
        if not rec.get("deny_reason"):
            continue
        payload = rec.get("payload") or {}
        if str(payload.get("command", "")).strip() != want:
            continue
        stamp = str(rec.get("resolved_at", ""))
        if stamp >= when:
            newest, when = str(rec["deny_reason"]), stamp
    return newest


def review_cli() -> int:
    pending = risk.sort_by_risk(reviewable_pending())
    if not pending:
        print("No pending approvals.")
        return 0
    print(f"{len(pending)} pending action(s) (highest-risk first).\n")
    for rec in pending:
        tier = risk.risk_for(rec.get("category", ""))
        print(f"── {risk.label(tier)} [{tier}/{rec['category']}] {rec['title']}")
        print(f"   {rec['description']}")
        print(f"   payload: {rec.get('payload')}")
        if rec.get("continuation") is not None:
            print(f"   then: {worker_hooks.describe(rec['continuation'])}")
        try:
            choice = input("   approve? [y]es / [n]o / [s]kip: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nstopped.")
            break
        if choice in ("y", "yes"):
            res = approve(rec["id"])
            print(f"   ✓ {res.get('result', res)}\n")
        elif choice in ("n", "no"):
            why = ""
            try:
                why = input("   why? (optional, helps the agent) "
                            ).strip()
            except (EOFError, KeyboardInterrupt):
                why = ""
            reject(rec["id"], reason=why)
            print("   ✗ rejected\n")
        else:
            print("   … skipped\n")
    return 0
