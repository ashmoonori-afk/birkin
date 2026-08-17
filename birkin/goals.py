"""Persisted session goals, token accounting, and approval-gated verifiers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import approvals, config, store

_STATUSES = frozenset({"active", "paused", "done"})
_SLUG_RE = re.compile(r"[\W_]+", re.UNICODE)
_OBJECTIVE_DISPLAY = 48
_OBJECTIVE_PROMPT = 500
_GATE_OUTPUT_TAIL = 2000


@dataclass(frozen=True)
class GoalState:
    slug: str
    objective: str
    tokens_used: int
    status: str
    gate_cmd: str | None
    gate_last: dict[str, Any] | None
    created_at: str
    updated_at: str
    session_id: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(objective: str, limit: int = 48) -> str:
    normalized = _SLUG_RE.sub("-", objective.lower()).strip("-")
    if not normalized:
        return "goal-" + hashlib.sha256(objective.encode("utf-8")).hexdigest()[:12]
    if len(normalized) <= limit:
        return normalized
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    return f"{normalized[:limit - 9].rstrip('-')}-{digest}"


def _path(slug: str, session_id: str | None = None) -> Path:
    if session_id is None:
        return config.goals_dir() / f"{slug}.json"
    digest = hashlib.sha256(session_id.encode()).hexdigest()[:12]
    return config.goals_dir() / f"{slug}--{digest}.json"


def _domain_lock() -> store.file_lock:
    return store.file_lock(config.goals_dir() / ".active")


def _decode(value: Any) -> GoalState | None:
    if not isinstance(value, dict):
        return None
    try:
        state = GoalState(
            slug=str(value["slug"]),
            objective=str(value["objective"]),
            tokens_used=int(value.get("tokens_used", 0)),
            status=str(value["status"]),
            gate_cmd=(str(value["gate_cmd"]) if value.get("gate_cmd") is not None
                      else None),
            gate_last=(dict(value["gate_last"])
                       if isinstance(value.get("gate_last"), dict) else None),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            session_id=(
                str(value["session_id"])
                if isinstance(value.get("session_id"), str)
                else None
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if (not state.slug or not state.objective.strip()
            or state.status not in _STATUSES or state.tokens_used < 0):
        return None
    return state


def _load(path: Path) -> GoalState | None:
    return _decode(store._read_json(path, None))


def _save(state: GoalState) -> GoalState:
    payload = asdict(state)
    if state.session_id is None:
        payload.pop("session_id")
    store._write_json(_path(state.slug, state.session_id), payload)
    return state


def _active_unlocked(session_id: str | None = None) -> GoalState | None:
    active = []
    for path in config.goals_dir().glob("*.json"):
        state = _load(path)
        if (state is not None and state.status == "active"
                and state.session_id == session_id):
            active.append(state)
    if not active:
        return None
    return max(active, key=lambda state: (state.updated_at, state.created_at,
                                          state.slug))


def set_goal(
    objective: str,
    gate: str | None = None,
    *,
    session_id: str | None = None,
) -> GoalState:
    """Create a new active goal, pausing any currently active goal."""
    objective = str(objective or "").strip()
    if not objective:
        raise ValueError("goal objective must not be empty")
    gate_cmd = str(gate).strip() if gate is not None else None
    gate_cmd = gate_cmd or None
    if session_id is not None:
        from . import harness
        session_id = harness.validate_working_session_id(session_id)
    now = _now()
    state = GoalState(
        slug=_slug(objective), objective=objective,
        tokens_used=0, status="active", gate_cmd=gate_cmd, gate_last=None,
        created_at=now, updated_at=now, session_id=session_id)
    with _domain_lock():
        snapshot: dict[Path, GoalState] = {}
        for path in config.goals_dir().glob("*.json"):
            with store.file_lock(path):
                current = _load(path)
                if current is not None and current.session_id == session_id:
                    snapshot[path] = current
        target = _path(state.slug, session_id)
        try:
            for current in snapshot.values():
                if (current.status == "active"
                        and current.slug != state.slug):
                    _save(replace(current, status="paused", updated_at=now))
            _save(state)
        except BaseException:
            try:
                if target not in snapshot:
                    with store.file_lock(target):
                        target.unlink(missing_ok=True)
                for previous in snapshot.values():
                    _save(previous)
            except BaseException as rollback_exc:
                raise RuntimeError(
                    "goal update failed and rollback failed"
                ) from rollback_exc
            raise
    return state


def get_active(*, session_id: str | None = None) -> GoalState | None:
    """Return the active goal, if one exists."""
    with _domain_lock():
        return _active_unlocked(session_id)


def validate_snapshot(
    value: dict[str, Any] | None,
    *,
    session_id: str,
) -> GoalState | None:
    """Decode a canonical goal snapshot without mutating persisted state."""
    from . import harness

    session = harness.validate_working_session_id(session_id)
    if value is None:
        return None
    restored = _decode({**value, "session_id": session})
    if restored is None:
        raise ValueError("goal snapshot is malformed")
    return restored


def restore_snapshot(
    value: dict[str, Any] | None,
    *,
    session_id: str,
) -> GoalState | None:
    """Restore one canonical session goal snapshot."""
    restored = validate_snapshot(value, session_id=session_id)
    with _domain_lock():
        active = _active_unlocked(session_id)
        try:
            if active is not None:
                _save(replace(active, status="paused", updated_at=_now()))
            if restored is None:
                return None
            return _save(restored)
        except BaseException:
            if active is not None:
                _save(active)
            raise


def add_usage(
    input_tokens: int,
    output_tokens: int,
    *,
    session_id: str | None = None,
) -> GoalState | None:
    """Accumulate one turn's token usage onto the active goal."""
    input_count = max(0, int(input_tokens))
    output_count = max(0, int(output_tokens))
    with _domain_lock():
        active = _active_unlocked(session_id)
        if active is None:
            return None
        path = _path(active.slug, active.session_id)
        with store.file_lock(path):
            current = _load(path)
            if current is None or current.status != "active":
                return None
            updated = replace(
                current,
                tokens_used=current.tokens_used + input_count + output_count,
                updated_at=_now(),
            )
            return _save(updated)


def _transition(
    status: str, *, session_id: str | None = None
) -> GoalState | None:
    with _domain_lock():
        current = _active_unlocked(session_id)
        if current is None:
            return None
        path = _path(current.slug, current.session_id)
        with store.file_lock(path):
            latest = _load(path)
            if latest is None or latest.status != "active":
                return None
            try:
                return _save(
                    replace(latest, status=status, updated_at=_now())
                )
            except BaseException:
                try:
                    _save(latest)
                except BaseException as rollback_exc:
                    raise RuntimeError(
                        f"goal {status} failed and rollback failed"
                    ) from rollback_exc
                raise


def pause(*, session_id: str | None = None) -> GoalState | None:
    """Pause the active goal."""
    return _transition("paused", session_id=session_id)


def done(*, session_id: str | None = None) -> GoalState | None:
    """Mark the active goal done."""
    return _transition("done", session_id=session_id)


def _short_objective(objective: str) -> str:
    one_line = " ".join(objective.split())
    if len(one_line) <= _OBJECTIVE_DISPLAY:
        return one_line
    return one_line[:_OBJECTIVE_DISPLAY - 3].rstrip() + "..."


def render_status() -> str:
    """Render the active goal as one compact statusline segment."""
    state = get_active()
    if state is None:
        return ""
    parts = [f"goal: {_short_objective(state.objective)}",
             f"{state.tokens_used} tokens"]
    if state.gate_cmd:
        if state.gate_last is None:
            gate = "pending"
        else:
            gate = "pass" if state.gate_last.get("ok") else "fail"
        parts.append(f"gate: {gate}")
    return " | ".join(parts)


def prompt_note(*, session_id: str | None = None) -> str:
    """The active goal as one system-prompt block (empty when there is none).

    Persisting a goal the model never sees is bookkeeping, not steering, so
    every prompt assembled through :mod:`promptgate` carries the objective and
    the verifier that will decide completion.
    """
    state = get_active(session_id=session_id)
    if state is None:
        return ""
    lines = [f"- objective: {' '.join(state.objective.split())[:_OBJECTIVE_PROMPT]}"]
    if state.gate_cmd:
        lines.append(f"- completion verifier: {state.gate_cmd[:200]}")
    body = "\n".join(lines)
    return ("\n\n## Active goal\n"
            "This session is working toward one persisted goal. Keep your work "
            "pointed at it, and say so when a request pulls away from it.\n"
            f"{body}\n")


def request_completion(state: GoalState,
                       cfg: dict[str, Any]) -> tuple[GoalState | None, str]:
    """Complete ``state`` only when its verifier actually passed.

    Returns ``(goal, outcome)`` where outcome is ``done``, ``queued`` (the
    verifier is sitting in the approval queue and nothing has been verified yet)
    or ``failed``. Both non-``done`` outcomes leave the goal open: a goal whose
    gate never ran is not a goal that was met.
    """
    if not (state.gate_cmd or "").strip():
        return done(session_id=state.session_id), "done"
    queued = not approvals.is_auto("shell", cfg)
    updated = run_gate(state, cfg)
    if queued:
        return updated, "queued"
    if not (updated.gate_last or {}).get("ok"):
        return updated, "failed"
    return done(session_id=state.session_id), "done"


def run_gate(state: GoalState, cfg: dict[str, Any]) -> GoalState:
    """Run or queue ``state``'s verifier through the shell approval pipeline.

    The command is never passed to subprocess here. Non-auto-approved shell
    actions are proposals; auto-approved actions use the approval executor that
    handles shell payloads everywhere else.
    """
    command = (state.gate_cmd or "").strip()
    if not command:
        return state
    if not approvals.is_auto("shell", cfg):
        approvals.propose(
            category="shell", title=f"goal verifier: {command[:60]}",
            description=f"Verify session goal '{state.objective[:120]}'.",
            payload={"command": command}, cfg=cfg, origin="goal")
        with _domain_lock():
            path = _path(state.slug, state.session_id)
            with store.file_lock(path):
                current = _load(path)
                if current is None:
                    return state
                if current.gate_cmd != command:
                    current = _save(replace(
                        current,
                        gate_cmd=command,
                        updated_at=_now(),
                    ))
                return current

    try:
        output = approvals.execute_action(
            "shell", {"command": command}, cfg=cfg)
        ok = str(output).startswith("[exit 0]")
    except Exception as exc:
        output = f"action failed: {exc}"
        ok = False
    gate_last = {"ok": ok, "output_tail": str(output)[-_GATE_OUTPUT_TAIL:],
                 "at": _now()}
    with _domain_lock():
        path = _path(state.slug, state.session_id)
        with store.file_lock(path):
            current = _load(path)
            if current is None:
                return state
            return _save(replace(
                current,
                gate_cmd=command,
                gate_last=gate_last,
                updated_at=_now(),
            ))
