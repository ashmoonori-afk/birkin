"""Human-in-the-loop approval gate for consequential actions.

Policy (configurable via the REPL ``/permission`` command):
- Categories in ``config["auto_approve"]`` (default ``memory``, ``skills``) are
  applied immediately.
- Everything else (e.g. ``cron``, ``shell``) is queued in
  ``~/.birkin/pending/`` and only executes after the user approves it with
  ``birkin review`` or the dashboard.

The agent and the Morpheus routine call :func:`propose`; they never execute
consequential actions directly.
"""

from __future__ import annotations

import subprocess
from typing import Any

from . import config, cron, risk, store
from .proc import shell_argv


def is_auto(category: str, cfg: dict[str, Any]) -> bool:
    return category in (cfg.get("auto_approve") or [])


def propose(*, category: str, title: str, description: str,
            payload: dict[str, Any], cfg: dict[str, Any],
            origin: str = "morpheus") -> dict[str, Any]:
    """Apply (if auto-approved) or queue an action. Returns a status dict."""
    if is_auto(category, cfg):
        result = execute_action(category, payload)
        return {"auto": True, "category": category, "result": result}
    rec = store.add_pending(category=category, title=title,
                            description=description, payload=payload,
                            origin=origin)
    return {"auto": False, "id": rec["id"], "title": title}


def execute_action(category: str, payload: dict[str, Any]) -> str:
    """Carry out an approved action. Returns a human-readable result."""
    if category == "cron":
        job = cron.add_job(
            name=payload.get("name", "job"),
            hour=int(payload.get("hour", 9)),
            minute=int(payload.get("minute", 0)),
            action_type=payload.get("type", "prompt"),
            value=payload.get("value", ""))
        return f"Registered cron job '{job['name']}' at " \
               f"{job['hour']:02d}:{job['minute']:02d} (id {job['id']})."
    if category == "shell":
        command = payload.get("command", "")
        if not command:
            return "No command to run."
        try:
            proc = subprocess.run(shell_argv(command), capture_output=True,
                                  text=True, errors="replace",
                                  timeout=int(payload.get("timeout", 300)))
        except subprocess.TimeoutExpired:
            return "Command timed out."
        out = (proc.stdout or "") + (proc.stderr or "")
        return f"[exit {proc.returncode}] {out[:2000]}"
    if category == "skill":
        from .skills.manager import apply_skill_proposal
        return apply_skill_proposal(payload)
    # memory is applied by the agent directly; nothing else has an executor.
    return f"(no executor for category '{category}')"


# -- CLI review ------------------------------------------------------------

def approve(aid: str) -> dict[str, Any]:
    rec = store.get_pending(aid)
    if not rec or rec.get("status") != "pending":
        return {"ok": False, "error": "not found or already resolved"}
    result = execute_action(rec["category"], rec.get("payload", {}))
    store.resolve_pending(aid, "approved")
    return {"ok": True, "result": result}


def reject(aid: str) -> dict[str, Any]:
    rec = store.resolve_pending(aid, "rejected")
    return {"ok": bool(rec)}


def review_cli() -> int:
    pending = risk.sort_by_risk(store.list_pending())
    if not pending:
        print("No pending approvals.")
        return 0
    print(f"{len(pending)} pending action(s) (highest-risk first).\n")
    for rec in pending:
        tier = risk.risk_for(rec.get("category", ""))
        print(f"── {risk.label(tier)} [{tier}/{rec['category']}] {rec['title']}")
        print(f"   {rec['description']}")
        print(f"   payload: {rec.get('payload')}")
        try:
            choice = input("   approve? [y]es / [n]o / [s]kip: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nstopped.")
            break
        if choice in ("y", "yes"):
            res = approve(rec["id"])
            print(f"   ✓ {res.get('result', res)}\n")
        elif choice in ("n", "no"):
            reject(rec["id"])
            print("   ✗ rejected\n")
        else:
            print("   … skipped\n")
    return 0
