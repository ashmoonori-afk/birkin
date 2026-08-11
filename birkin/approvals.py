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
from typing import Any

from . import config, cron, risk, store, worker_hooks
from .proc import shell_argv, shell_env


def is_auto(category: str, cfg: dict[str, Any]) -> bool:
    return category in (cfg.get("auto_approve") or [])


def worker_hook_contract() -> dict[str, Any]:
    return worker_hooks.contract()


def _is_shell_cron(category: str, payload: dict[str, Any]) -> bool:
    """A cron job whose payload runs a shell command — as dangerous as `shell`.

    The ``type`` is normalised (case/whitespace) so a capitalised ``"Shell"``
    can't slip a shell payload past this gate.
    """
    return category == "cron" and str(
        (payload or {}).get("type", "")).strip().lower() == "shell"


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
    auto = continuation is None and is_auto(category, cfg) and not (
        _is_shell_cron(category, payload) and not is_auto("shell", cfg))
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
        job = cron.add_job(
            name=payload.get("name", "job"),
            hour=_clk(payload.get("hour", 9), 9, 23),
            minute=_clk(payload.get("minute", 0), 0, 59),
            action_type=payload.get("type", "prompt"),
            value=payload.get("value", ""),
            deliver_chat_id=payload.get("deliver_chat_id"),
            schedule=str(schedule) if schedule else None)
        return f"Registered cron job '{job['name']}' at " \
               f"{cron.schedule_display(job)} (id {job['id']})."
    if category == "shell":
        command = payload.get("command", "")
        if not command:
            return "No command to run."
        try:
            to = payload.get("timeout", 300)
            try:                           # model/user payload may be non-int
                to = int(to)
            except (TypeError, ValueError):
                to = 300
            proc = subprocess.run(shell_argv(command), capture_output=True,
                                  text=True, errors="replace",
                                  timeout=max(1, min(3600, to)),
                                  env=shell_env(), check=False)
        except subprocess.TimeoutExpired:
            return "Command timed out."
        out = (proc.stdout or "") + (proc.stderr or "")
        return f"[exit {proc.returncode}] {out[:2000]}"
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
    # memory is applied by the agent directly; nothing else has an executor.
    return f"(no executor for category '{category}')"


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
