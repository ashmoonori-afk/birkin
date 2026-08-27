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

from . import (
    approval_dispatch,
    approval_execution,
    approval_questions,
    risk,
    store,
    worker_hooks,
)
from .proc import run_shell_command


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
        resolved = approve(
            rec["id"],
            approved_by="system:auto-approval",
            approved_via="policy:auto-approve",
        )
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
    return approval_questions.request_answers(
        title=title,
        description=description,
        questions=questions,
        origin=origin,
        timeout_seconds=timeout_seconds,
        allow_clarification=allow_clarification,
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
    return approval_questions.answer(
        aid,
        answers=answers,
        source=source,
        clarification=clarification,
        navigation=navigation,
        capability=capability,
        resume_token=resume_token,
        question_digest=question_digest,
        input_schema_version=input_schema_version,
        previous_state_digest=previous_state_digest,
    )


def execute_action(
    category: str,
    payload: dict[str, Any],
    cfg: dict[str, Any] | None = None,
    on_event: Any = None,
) -> str:
    """Carry out an action that already has durable approval authority."""
    return approval_dispatch.execute_action(
        category,
        payload,
        approval_dispatch.DispatchOptions(
            cfg=cfg,
            on_event=on_event,
            shell_runner=run_shell_command,
        ),
    )


# -- CLI review ------------------------------------------------------------

def reviewable_pending() -> list[dict[str, Any]]:
    return [rec for rec in store.list_pending()
            if rec.get("category") != "workflow"]


def claim(
    aid: str,
    *,
    approved_by: str,
    approved_via: str,
) -> dict[str, Any]:
    return approval_execution.claim(
        aid,
        approved_by=approved_by,
        approved_via=approved_via,
    )


def execute_claimed(aid: str, on_event: Any = None) -> dict[str, Any]:
    return approval_execution.execute_claimed(
        aid, execute_action, on_event=on_event
    )


def execute_continuation(aid: str, on_event: Any = None) -> dict[str, Any]:
    return approval_execution.execute_continuation(aid, on_event=on_event)


def restore_claim(aid: str) -> bool:
    return approval_execution.restore_claim(aid)


def approve(
    aid: str,
    on_event: Any = None,
    *,
    approved_by: str,
    approved_via: str,
) -> dict[str, Any]:
    return approval_execution.approve(
        aid,
        execute_action,
        on_event=on_event,
        approved_by=approved_by,
        approved_via=approved_via,
    )


def reject(
    aid: str,
    reason: str = "",
    *,
    rejected_by: str,
    rejected_via: str,
) -> dict[str, Any]:
    return approval_execution.reject(
        aid,
        reason=reason,
        rejected_by=rejected_by,
        rejected_via=rejected_via,
    )


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
            res = approve(
                rec["id"],
                approved_by="human:terminal",
                approved_via="terminal:review",
            )
            print(f"   ✓ {res.get('result', res)}\n")
        elif choice in ("n", "no"):
            why = ""
            try:
                why = input("   why? (optional, helps the agent) "
                            ).strip()
            except (EOFError, KeyboardInterrupt):
                why = ""
            reject(
                rec["id"],
                reason=why,
                rejected_by="human:terminal",
                rejected_via="terminal:review",
            )
            print("   ✗ rejected\n")
        else:
            print("   … skipped\n")
    return 0


__all__ = [
    "answer",
    "approve",
    "claim",
    "denial_reason_for",
    "execute_action",
    "execute_claimed",
    "execute_continuation",
    "is_auto",
    "propose",
    "reject",
    "request_answers",
    "restore_claim",
    "review_cli",
    "reviewable_pending",
    "run_shell_command",
    "subprocess",
    "worker_hook_contract",
]
