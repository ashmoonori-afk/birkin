"""Continual harness — the versioned ledger of birkin's self-improvement.

Morpheus and the in-session review pass no longer write memory/skills blindly:
they emit a *proposal* (summary, rationale, expectedOutcome, edits) and this
module validates, applies, records, and — when an edit turns out wrong —
reverses it. Four entry kinds are tracked: ``prompt`` (supplemental behaviour
notes), ``memory``, ``skill``, and ``subagent`` (reusable delegation specs).

Design: docs/prime-agent-analysis.html sections 4.2-4.5.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import config, store

KINDS = ("prompt", "memory", "skill", "subagent")
ACTIONS = ("create", "update", "delete")
SCOPES = ("local", "global")

MAX_EDITS = 12
MAX_CONTENT = 2000
RENDER_PER_KIND = 6
RENDER_HISTORY = 5
RENDER_WIDTH = 180

STATE_FILE = "harness_state.json"
HISTORY_FILE = "refinements.jsonl"

_KIND_HEADINGS = {
    "prompt": "행동 노트 (prompt)",
    "memory": "알고 있는 사실 (memory)",
    "skill": "보유 스킬 (skill)",
    "subagent": "위임 역할 (subagent)",
}


def harness_dir(scope: str = "global") -> Path:
    base = config.birkin_home() / "harness"
    return base if scope == "global" else base / "local"


def state_path(scope: str = "global") -> Path:
    return harness_dir(scope) / STATE_FILE


def history_path(scope: str = "global") -> Path:
    return harness_dir(scope) / HISTORY_FILE


def empty_state() -> dict[str, Any]:
    return {"schema": 1, "entries": {kind: {} for kind in KINDS},
            "refinements": []}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str = "rf") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:4]}"


def slug(raw: str, fallback: str = "entry") -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(raw).strip().lower())
    return cleaned.strip("_")[:80] or fallback


def load(scope: str = "global") -> dict[str, Any]:
    """Read the harness state, degrading to empty on anything unreadable.

    This runs on every system-prompt build, so a corrupt file must never break
    a session; the next save rewrites it cleanly.
    """
    state = empty_state()
    raw = store._read_json(state_path(scope), None)
    if not isinstance(raw, dict):
        return state
    schema = raw.get("schema")
    state["schema"] = schema if isinstance(schema, int) else 1
    entries = raw.get("entries")
    if isinstance(entries, dict):
        for kind in KINDS:
            records = entries.get(kind)
            if not isinstance(records, dict):
                continue
            for eid, entry in records.items():
                if isinstance(entry, dict):
                    state["entries"][kind][str(eid)] = entry
    refinements = raw.get("refinements")
    if isinstance(refinements, list):
        state["refinements"] = [r for r in refinements if isinstance(r, dict)]
    return state


def save(state: dict[str, Any], scope: str = "global") -> Path:
    path = state_path(scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    with store.file_lock(path):
        store._write_json(path, state)
    return path


def history(scope: str = "global", limit: int | None = None) -> list[dict[str, Any]]:
    path = history_path(scope)
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("id"):
            events.append(event)
    return events[-limit:] if limit else events


def _append_history(event: dict[str, Any], scope: str) -> None:
    path = history_path(scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def _policy_markers() -> tuple[str, ...]:
    from . import prompts
    return (prompts.UI_COMPONENT_POLICY_OPEN, prompts.UI_COMPONENT_POLICY_CLOSE,
            prompts.RESEARCH_EVIDENCE_OPEN, prompts.RESEARCH_EVIDENCE_CLOSE)


def validate_edit(edit: Any, *, max_content: int = MAX_CONTENT) -> str | None:
    """Return an error string, or None when the edit is structurally sound."""
    if not isinstance(edit, dict):
        return "edit must be an object"
    action = str(edit.get("action", "")).strip().lower()
    if action not in ACTIONS:
        return f"unknown action {action!r}"
    kind = str(edit.get("kind", "")).strip().lower()
    if kind not in KINDS:
        return f"unknown kind {kind!r}"
    if action == "delete":
        return None if edit.get("id") else "delete needs an id"
    if action == "update" and not edit.get("id"):
        return "update needs an id"
    if action == "create" and not str(edit.get("title", "")).strip():
        return "create needs a title"
    content = edit.get("content")
    if action == "create" and not str(content or "").strip():
        return "create needs content"
    if content is not None and len(str(content)) > max_content:
        return f"content too long ({len(str(content))} > {max_content})"
    # Every entry title and body is rendered into the system prompt, regardless
    # of kind, so none may forge, close, or reopen a sealed policy block.
    for field in ("title", "content"):
        text = edit.get(field)
        if text and any(marker in str(text) for marker in _policy_markers()):
            if kind == "prompt" and field == "content":
                return "prompt content may not contain a policy tag"
            return f"{field} may not contain a policy tag"
    return None


def _merge_entry(before: dict[str, Any] | None, edit: dict[str, Any], *,
                 eid: str, kind: str, scope: str, source: str) -> dict[str, Any]:
    def pick(field: str, default: Any) -> Any:
        if edit.get(field) is not None:
            return edit[field]
        return before.get(field, default) if before else default

    return {
        "id": eid,
        "kind": kind,
        "title": str(pick("title", eid)),
        "content": str(pick("content", "")),
        "path": str(pick("path", "general")),
        "scope": (before or {}).get("scope") or scope,
        "reference": pick("reference", {}) or {},
        "arguments": pick("arguments", {}) or {},
        "metadata": pick("metadata", {}) or {},
        "source": source,
        "created_at": (before or {}).get("created_at") or _now(),
        "updated_at": _now(),
        "version": (before.get("version", 0) + 1) if before else 1,
    }


def apply(state: dict[str, Any], proposal: dict[str, Any], *,
          baseline: dict[str, Any] | None = None, scope: str = "global",
          rid: str | None = None, source: str = "harness",
          max_edits: int = MAX_EDITS, max_content: int = MAX_CONTENT,
          rollback_of: str | None = None,
          persist: bool = True) -> dict[str, Any]:
    """Apply a proposal edit-by-edit. Partial failure is the normal path."""
    rid = rid or new_id()
    edits = proposal.get("edits")
    edits = list(edits)[:max_edits] if isinstance(edits, list) else []
    applied: list[dict[str, Any]] = []
    touched: set[str] = set()

    for edit in edits:
        error = validate_edit(edit, max_content=max_content)
        if error:
            record = dict(edit) if isinstance(edit, dict) else {"edit": edit}
            applied.append({**record, "applied": False, "error": error})
            continue

        kind = str(edit["kind"]).strip().lower()
        action = str(edit["action"]).strip().lower()
        eid = str(edit.get("id") or slug(edit.get("title", ""), kind))
        records = state["entries"][kind]
        before = copy.deepcopy(records.get(eid))
        key = f"{kind}:{eid}"

        # Optimistic concurrency: the planner reasoned about `baseline`; if the
        # entry moved since then (a user edit, a parallel pass), drop this edit
        # rather than clobber the newer value.
        if baseline is not None and key not in touched:
            base = baseline.get("entries", {}).get(kind, {}).get(eid)
            if before != base:
                applied.append({**edit, "id": eid, "before": before,
                                "applied": False,
                                "error": "entry changed during planning"})
                continue

        if action == "delete":
            if not before:
                applied.append({**edit, "id": eid, "applied": False,
                                "error": "entry not found"})
                continue
            del records[eid]
            touched.add(key)
            applied.append({**edit, "id": eid, "before": before, "after": None,
                            "applied": True})
            continue

        if action == "create" and before:
            applied.append({**edit, "id": eid, "before": before,
                            "applied": False, "error": "entry already exists"})
            continue
        if action == "update" and not before:
            applied.append({**edit, "id": eid, "applied": False,
                            "error": "entry not found"})
            continue

        after = _merge_entry(before, edit, eid=eid, kind=kind, scope=scope,
                             source=source)
        records[eid] = after
        touched.add(key)
        applied.append({**edit, "id": eid, "before": before,
                        "after": copy.deepcopy(after), "applied": True})

    changes = [f"{e['action']} {e['kind']}:{e['id']}"
               for e in applied if e.get("applied")]
    event = {
        "id": rid,
        "trigger": str(proposal.get("summary", ""))[:400],
        "changes": changes,
        "evidence": str(proposal.get("rationale", ""))[:400],
        "outcome": str(proposal.get("expectedOutcome", ""))[:400],
        "applied": applied,
        "scope": scope,
        "created_at": _now(),
    }
    if rollback_of:
        event["rollback_of"] = rollback_of

    state["refinements"] = (state.get("refinements") or [])[-19:] + [event]
    if persist:
        save(state, scope)
        _append_history(event, scope)
    return event


def _inverse_edits(event: dict[str, Any]) -> list[dict[str, Any]]:
    inverse: list[dict[str, Any]] = []
    for entry in reversed(event.get("applied") or []):
        if not entry.get("applied"):
            continue
        before, after = entry.get("before"), entry.get("after")
        kind, eid = entry["kind"], entry["id"]
        if before is None:
            inverse.append({"action": "delete", "kind": kind, "id": eid,
                            "reason": f"rollback of {event['id']}"})
        else:
            action = "update" if after is not None else "create"
            inverse.append({"action": action, "kind": kind, "id": eid,
                            "title": before.get("title", eid),
                            "content": before.get("content", ""),
                            "path": before.get("path", "general"),
                            "reference": before.get("reference", {}),
                            "arguments": before.get("arguments", {}),
                            "metadata": before.get("metadata", {}),
                            "reason": f"rollback of {event['id']}"})
    return inverse


def find_event(rid: str, scope: str = "global") -> dict[str, Any]:
    for event in reversed(history(scope)):
        if event.get("id") == rid:
            return event
    raise KeyError(f"no refinement with id {rid!r}")


def rollback(rid: str, scope: str = "global") -> dict[str, Any]:
    """Undo a refinement by replaying its applied edits in reverse."""
    target = find_event(rid, scope)
    inverse = _inverse_edits(target)
    state = load(scope)
    return apply(state, {"summary": f"rollback of {rid}",
                         "rationale": target.get("trigger", ""),
                         "expectedOutcome": "이전 harness 상태 복원",
                         "edits": inverse},
                 baseline=None, scope=scope, rid=new_id(),
                 source="rollback", max_edits=max(len(inverse), MAX_EDITS),
                 rollback_of=rid)


def auto_kinds(cfg: dict[str, Any] | None) -> set[str]:
    raw = (cfg or {}).get("harness_auto_approve")
    if raw is None:
        raw = ["memory", "skill"]
    return {str(kind).strip().lower() for kind in raw}


def submit(proposal: dict[str, Any], *, cfg: dict[str, Any] | None = None,
           scope: str = "global", source: str = "harness",
           rid: str | None = None,
           origin: str = "harness") -> dict[str, Any]:
    """Route a proposal through the approval gate, then apply what may auto-apply.

    Returns ``{"applied": event|None, "queued": [status], "rejected": [edit]}``.
    An edit whose kind is not in ``harness_auto_approve`` is queued for
    ``birkin review`` and is NOT written now; a structurally invalid edit is
    rejected outright rather than queued, so a human never reviews garbage.
    """
    from . import approvals

    cfg = cfg if cfg is not None else config.load_config()
    max_edits = int(cfg.get("harness_max_edits") or MAX_EDITS)
    raw_edits = proposal.get("edits")
    edits = list(raw_edits)[:max_edits] if isinstance(raw_edits, list) else []
    auto = auto_kinds(cfg)

    auto_edits: list[dict[str, Any]] = []
    queued: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for edit in edits:
        error = validate_edit(edit, max_content=MAX_CONTENT)
        if error:
            record = dict(edit) if isinstance(edit, dict) else {"edit": edit}
            rejected.append({**record, "applied": False, "error": error})
            continue
        kind = str(edit["kind"]).strip().lower()
        if kind in auto:
            auto_edits.append(edit)
            continue
        label = edit.get("title") or edit.get("id") or kind
        queued.append(approvals.propose(
            category="harness",
            title=f"harness {edit['action']} {kind}: {label}",
            description=str(edit.get("reason")
                            or proposal.get("rationale") or "")[:400],
            payload={"edit": edit, "scope": scope,
                     "summary": proposal.get("summary", ""),
                     "rationale": proposal.get("rationale", ""),
                     "expectedOutcome": proposal.get("expectedOutcome", "")},
            cfg=cfg, origin=origin))

    applied: dict[str, Any] | None = None
    if auto_edits:
        applied = apply(load(scope), {**proposal, "edits": auto_edits},
                        baseline=load(scope), scope=scope, rid=rid,
                        source=source, max_edits=max_edits)
    return {"applied": applied, "queued": queued, "rejected": rejected}


def apply_approved_edit(payload: dict[str, Any]) -> str:
    """Executor for an approved ``harness`` proposal (see approvals.execute_action).

    Raises on a rejected edit: :func:`approvals.execute_claimed` reads a raised
    exception as failure and a returned string as success, so a silently
    dropped edit must not look approved.
    """
    edit = (payload or {}).get("edit")
    if not isinstance(edit, dict):
        raise ValueError("harness approval carries no edit")
    scope = str((payload or {}).get("scope") or "global")
    summary = str(payload.get("summary")
                  or f"approved {edit.get('action')} {edit.get('kind')}")
    event = apply(load(scope),
                  {"summary": summary,
                   "rationale": payload.get("rationale", ""),
                   "expectedOutcome": payload.get("expectedOutcome", ""),
                   "edits": [edit]},
                  baseline=None, scope=scope, rid=new_id(), source="approval")
    outcome = event["applied"][0]
    if not outcome.get("applied"):
        raise ValueError(f"harness edit rejected: {outcome.get('error')}")
    return (f"Applied harness {outcome['action']} "
            f"{outcome['kind']}:{outcome['id']} (refinement {event['id']}).")


def _clip(text: str, width: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= width else flat[:width - 1] + "…"


def merge_states(*states: dict[str, Any]) -> dict[str, Any]:
    merged = empty_state()
    for state in states:
        for kind in KINDS:
            for eid, entry in (state.get("entries", {}).get(kind) or {}).items():
                key = eid if eid not in merged["entries"][kind] else \
                    f"{entry.get('scope', 'local')}:{eid}"
                merged["entries"][kind][key] = entry
        merged["refinements"].extend(state.get("refinements") or [])
    merged["refinements"].sort(key=lambda e: str(e.get("created_at", "")))
    return merged


def render_block(state: dict[str, Any], *, per_kind: int = RENDER_PER_KIND,
                 history_limit: int = RENDER_HISTORY,
                 width: int = RENDER_WIDTH,
                 budget: int | None = None) -> str:
    """Compact the harness into the system-prompt block (empty when unused)."""
    entries = state.get("entries") or {}
    refinements = state.get("refinements") or []
    if not any(entries.get(kind) for kind in KINDS) and not refinements:
        return ""

    lines = ["## Harness (자가개선 상태)",
             "아래는 요약이다. 라우팅 힌트로 쓰고 상세가 필요하면 조회하라."]

    for kind in KINDS:
        records = entries.get(kind) or {}
        if not records:
            continue
        ordered = sorted(records.values(),
                         key=lambda e: str(e.get("updated_at", "")), reverse=True)
        lines.append("")
        lines.append(f"### {_KIND_HEADINGS[kind]}")
        for entry in ordered[:per_kind]:
            scope = entry.get("scope", "global")
            title = _clip(entry.get("title", entry.get("id", "?")), 80)
            body = _clip(entry.get("content", ""), width)
            version = entry.get("version", 1)
            lines.append(f"- [{scope}] {title} — {body} (v{version})")

    recent = refinements[-history_limit:]
    if recent:
        lines.append("")
        lines.append("### 최근 정련")
        for event in recent:
            trigger = _clip(event.get("trigger", ""), 120)
            changes = ", ".join(event.get("changes") or []) or "(적용 없음)"
            lines.append(f"- {event.get('id')} {trigger} → {_clip(changes, width)}")
            outcome = _clip(event.get("outcome", ""), 120)
            if outcome:
                lines.append(f"  기대: {outcome}")

    block = "\n".join(lines)
    if budget and len(block) > budget:
        block = block[:budget].rsplit("\n", 1)[0] + "\n- (예산 초과분 생략)"
    return block


def entry_titles(state: dict[str, Any], kind: str) -> Iterable[str]:
    return (e.get("title", "") for e in (state.get("entries", {}).get(kind) or {}).values())
