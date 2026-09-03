"""Continual harness — the versioned ledger of birkin's self-improvement.

Morpheus and the in-session review pass no longer write harness notes blindly:
they emit a *proposal* (summary, rationale, expectedOutcome, edits) and this
module validates, applies, records, and — when an edit turns out wrong —
reverses it. Four entry kinds are tracked: ``prompt`` (supplemental behaviour
notes), ``memory``, ``skill_note`` (non-executable metadata), and ``subagent``
(reusable delegation specs).

Design: docs/prime-agent-analysis.html sections 4.2-4.5.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from . import config, private_storage, store

KINDS = ("prompt", "memory", "skill_note", "subagent")
ACTIONS = ("create", "update", "delete")
SCOPES = ("local", "global")

MAX_EDITS = 12
MAX_CONTENT = 2000
RENDER_PER_KIND = 6
RENDER_HISTORY = 5
RENDER_WIDTH = 180
WORKING_FIELDS = (
    "corrections",
    "constraints",
    "decisions",
    "incomplete",
    "evidence",
    "next_actions",
)
WORKING_MAX_ITEM = 2000
WORKING_MAX_RENDER = 20_000
WORKING_MAX_VALUES = 256
REFINE_REQUEST_MAX_TEXT = 4000
REFINE_REQUEST_MAX_BYTES = 40_000
REFINE_REQUEST_QUERY_LIMIT = 100
_WORKING_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REFINE_REQUEST_ID = re.compile(r"^rr_[0-9]{8}-[0-9]{6}_[0-9a-f]{16}$")

STATE_FILE = "harness_state.json"
HISTORY_FILE = "refinements.jsonl"
REFINE_REQUESTS_DIR = "refine_requests"

_KIND_HEADINGS = {
    "prompt": "행동 노트 (prompt)",
    "memory": "알고 있는 사실 (memory)",
    "skill_note": "스킬 노트 (skill_note, 실행 불가)",
    "subagent": "위임 역할 (subagent)",
}


def _session_key(session_id: str | None) -> str:
    raw = str(session_id or "default")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw)
    label = cleaned.strip("._-").lower()[:64] or "session"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return f"{label}--{digest}"


def _legacy_session_key(session_id: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(session_id or "default"))
    return cleaned.strip("._-")[:120] or "default"


def harness_dir(scope: str = "global", *, session_id: str | None = None) -> Path:
    if scope == "global":
        return config.birkin_home() / "harness"
    sessions = config.sessions_dir()
    target = sessions / _session_key(session_id) / "harness"
    raw_session = str(session_id or "default")
    legacy_key = _legacy_session_key(session_id)
    if raw_session != legacy_key:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_digest = hashlib.sha256(legacy_key.casefold().encode()).hexdigest()[:24]
    migration_lock = sessions / f".harness-migration-{lock_digest}"
    with store.file_lock(migration_lock):
        try:
            legacy_session = next(
                candidate
                for candidate in sessions.iterdir()
                if candidate.is_dir() and candidate.name == raw_session
            )
        except (FileNotFoundError, StopIteration):
            return target
        legacy = legacy_session / "harness"
        if legacy.is_dir() and target.exists():
            raise RuntimeError(
                f"legacy and hashed harness state both exist for {raw_session!r}"
            )
        if legacy.is_dir() and not target.exists():
            try:
                legacy.rename(target)
            except OSError:
                return legacy
            try:
                legacy_session.rmdir()
            except OSError:
                pass
    return target


def state_path(scope: str = "global", *, session_id: str | None = None) -> Path:
    return harness_dir(scope, session_id=session_id) / STATE_FILE


@contextmanager
def working_transaction(session_id: str):
    session = validate_working_session_id(session_id)
    directory = harness_dir("local", session_id=session)
    directory.mkdir(parents=True, exist_ok=True)
    with store.file_lock(directory / ".working-transaction"):
        yield


def history_path(scope: str = "global", *, session_id: str | None = None) -> Path:
    return harness_dir(scope, session_id=session_id) / HISTORY_FILE


def refine_requests_dir(
    scope: str = "global", *, session_id: str | None = None
) -> Path:
    return harness_dir(scope, session_id=session_id) / REFINE_REQUESTS_DIR


def refine_request_path(
    request_id: str,
    scope: str = "global",
    *,
    session_id: str | None = None,
) -> Path:
    if not _REFINE_REQUEST_ID.fullmatch(request_id):
        raise ValueError("invalid refine request id")
    return refine_requests_dir(scope, session_id=session_id) / f"{request_id}.json"


def _refine_target(target: str) -> str:
    if not isinstance(target, str):
        raise ValueError("refine target must be text")
    normalized = " ".join(target.split()).strip()
    if not normalized:
        raise ValueError("refine target must not be empty")
    if len(normalized) > REFINE_REQUEST_MAX_TEXT:
        raise ValueError(
            f"refine target must be at most {REFINE_REQUEST_MAX_TEXT} characters"
        )
    return normalized


def _refine_scope(scope: str) -> str:
    if scope not in SCOPES:
        raise ValueError("refine scope must be local or global")
    return scope


def refine_request_digest(target: str, scope: str) -> str:
    normalized = _refine_target(target)
    selected_scope = _refine_scope(scope)
    canonical = json.dumps(
        {
            "worker": "harness",
            "action": "refine",
            "target": normalized,
            "scope": selected_scope,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def record_refine_request(
    target: str,
    *,
    scope: str = "global",
    session_id: str | None = None,
) -> tuple[dict[str, object], Path]:
    """Persist one structured refine request without applying it."""
    instructions = _refine_target(target)
    selected_scope = _refine_scope(scope)
    selected_session: str | None = None
    if selected_scope == "local":
        selected_session = validate_working_session_id(session_id or "default")
    stamp = datetime.now(timezone.utc)
    request_id = f"rr_{stamp.strftime('%Y%m%d-%H%M%S')}_{uuid.uuid4().hex[:16]}"
    artifact: dict[str, object] = {
        "schema": 2,
        "id": request_id,
        "target": instructions,
        "instructions": instructions,
        "scope": selected_scope,
        "session_id": selected_session,
        "created_at": stamp.isoformat(timespec="seconds"),
        "status": "recorded",
        "request_digest": refine_request_digest(instructions, selected_scope),
    }
    encoded = (
        json.dumps(
            artifact,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if len(encoded.encode("utf-8")) > REFINE_REQUEST_MAX_BYTES:
        raise ValueError("refine request artifact exceeds its storage bound")
    path = refine_request_path(
        request_id,
        selected_scope,
        session_id=selected_session,
    )
    private_storage.atomic_write_private_text(path, encoded)
    return artifact, path


def refine_requests(
    scope: str = "global",
    *,
    session_id: str | None = None,
    limit: int = REFINE_REQUEST_QUERY_LIMIT,
) -> list[dict[str, object]]:
    """Query recent valid refine-request artifacts in deterministic order."""
    selected_scope = _refine_scope(scope)
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= REFINE_REQUEST_QUERY_LIMIT
    ):
        raise ValueError(
            f"refine request limit must be from 1 to {REFINE_REQUEST_QUERY_LIMIT}"
        )
    directory = refine_requests_dir(selected_scope, session_id=session_id)
    if not directory.is_dir():
        return []
    records: list[dict[str, object]] = []
    for path in sorted(directory.glob("rr_*.json"))[-limit:]:
        if not _REFINE_REQUEST_ID.fullmatch(path.stem):
            continue
        try:
            raw_text = private_storage.read_private_text(path)
            if len(raw_text.encode("utf-8")) > REFINE_REQUEST_MAX_BYTES:
                continue
            raw = json.loads(raw_text)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        request_id = raw.get("id")
        target_value = raw.get("target")
        artifact_scope = raw.get("scope")
        created_at = raw.get("created_at")
        request_digest = raw.get("request_digest")
        expected_session = (
            validate_working_session_id(session_id or "default")
            if selected_scope == "local"
            else None
        )
        if (
            set(raw)
            != {
                "schema",
                "id",
                "target",
                "instructions",
                "scope",
                "session_id",
                "created_at",
                "status",
                "request_digest",
            }
            or raw.get("schema") != 2
            or not isinstance(request_id, str)
            or request_id != path.stem
            or not isinstance(target_value, str)
            or target_value != " ".join(target_value.split()).strip()
            or not target_value
            or len(target_value) > REFINE_REQUEST_MAX_TEXT
            or raw.get("instructions") != target_value
            or artifact_scope != selected_scope
            or raw.get("session_id") != expected_session
            or not isinstance(created_at, str)
            or not created_at
            or len(created_at) > 64
            or raw.get("status") != "recorded"
            or not isinstance(request_digest, str)
            or request_digest != refine_request_digest(target_value, selected_scope)
        ):
            continue
        records.append({str(key): value for key, value in raw.items()})
    records.sort(key=lambda item: (str(item.get("created_at", "")), str(item["id"])))
    return records[-limit:]


def empty_working() -> dict[str, Any]:
    return {
        "revision": 0,
        "updated_at": "",
        **{field: [] for field in WORKING_FIELDS},
    }


def _working_is_empty(working: dict[str, Any]) -> bool:
    """Emptiness is field content, never revision 0: a cleared journal keeps its
    revision so the optimistic-concurrency token stays monotonic."""
    return not any(working.get(field) for field in WORKING_FIELDS)


def empty_state() -> dict[str, Any]:
    return {
        "schema": 3,
        "entries": {kind: {} for kind in KINDS},
        "refinements": [],
        "working": empty_working(),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str = "rf") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:4]}"


def slug(raw: str, fallback: str = "entry") -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(raw).strip().lower())
    return cleaned.strip("_")[:80] or fallback


def _decode_state(raw: object) -> dict[str, Any]:
    state = empty_state()
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
        legacy = entries.get("skill")
        if isinstance(legacy, dict):
            for eid, entry in legacy.items():
                if isinstance(entry, dict):
                    state["entries"]["skill_note"][str(eid)] = {
                        **entry,
                        "kind": "skill_note",
                    }
    state["schema"] = 3
    refinements = raw.get("refinements")
    if isinstance(refinements, list):
        state["refinements"] = [r for r in refinements if isinstance(r, dict)]
    state["working"] = _decode_working(raw.get("working"))
    return state


def load(scope: str = "global", *, session_id: str | None = None) -> dict[str, Any]:
    """Read the harness state, degrading to empty on anything unreadable.

    This runs on every system-prompt build, so a corrupt file must never break
    a session; the next save rewrites it cleanly.
    """
    raw = store._read_json(state_path(scope, session_id=session_id), None)
    return _decode_state(raw)


def save(
    state: dict[str, Any], scope: str = "global", *, session_id: str | None = None
) -> Path:
    path = state_path(scope, session_id=session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = copy.deepcopy(state)
    with store.file_lock(path):
        latest = store._read_json(path, None)
        if isinstance(latest, dict):
            payload["working"] = _decode_working(latest.get("working"))
        store._write_json(path, payload)
    return path


def history(
    scope: str = "global", limit: int | None = None, *, session_id: str | None = None
) -> list[dict[str, Any]]:
    path = history_path(scope, session_id=session_id)
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


def _append_history(
    event: dict[str, Any], scope: str, *, session_id: str | None = None
) -> None:
    path = history_path(scope, session_id=session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def _policy_markers() -> tuple[str, ...]:
    from . import prompts

    return (
        prompts.UI_COMPONENT_POLICY_OPEN,
        prompts.UI_COMPONENT_POLICY_CLOSE,
        prompts.RESEARCH_EVIDENCE_OPEN,
        prompts.RESEARCH_EVIDENCE_CLOSE,
    )


def validate_edit(edit: Any, *, max_content: int = MAX_CONTENT) -> str | None:
    """Return an error string, or None when the edit is structurally sound."""
    if not isinstance(edit, dict):
        return "edit must be an object"
    action = str(edit.get("action", "")).strip().lower()
    if action not in ACTIONS:
        return f"unknown action {action!r}"
    kind = str(edit.get("kind", "")).strip().lower()
    if kind == "skill":
        return "kind 'skill' is not executable; use 'skill_note' for harness metadata"
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
    if action != "delete" and kind in {"memory", "skill"}:
        from .persistence_safety import unsafe_persistence_reason

        unsafe = unsafe_persistence_reason(edit.get("title"), content)
        if unsafe:
            return f"content {unsafe}"
    # Every entry title and body is rendered into the system prompt, regardless
    # of kind, so none may forge, close, or reopen a sealed policy block.
    for field in ("title", "content"):
        text = edit.get(field)
        if text and any(marker in str(text) for marker in _policy_markers()):
            if kind == "prompt" and field == "content":
                return "prompt content may not contain a policy tag"
            return f"{field} may not contain a policy tag"
    return None


def _merge_entry(
    before: dict[str, Any] | None,
    edit: dict[str, Any],
    *,
    eid: str,
    kind: str,
    scope: str,
    source: str,
) -> dict[str, Any]:
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


def apply(
    state: dict[str, Any],
    proposal: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
    scope: str = "global",
    session_id: str | None = None,
    rid: str | None = None,
    source: str = "harness",
    max_edits: int = MAX_EDITS,
    max_content: int = MAX_CONTENT,
    rollback_of: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Apply a proposal edit-by-edit. Partial failure is the normal path."""
    if persist:
        path = state_path(scope, session_id=session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with store.file_lock(path):
            raw = store._read_json(path, None)
            current = (
                _decode_state(raw) if isinstance(raw, dict) else copy.deepcopy(state)
            )
            event = _apply_unpersisted(
                current,
                proposal,
                baseline=baseline,
                scope=scope,
                session_id=session_id,
                rid=rid,
                source=source,
                max_edits=max_edits,
                max_content=max_content,
                rollback_of=rollback_of,
                persist=False,
            )
            original = copy.deepcopy(
                _decode_state(raw) if isinstance(raw, dict) else state
            )
            history = history_path(scope, session_id=session_id)
            try:
                history_before = history.read_bytes()
                history_existed = True
            except FileNotFoundError:
                history_before = b""
                history_existed = False
            store._write_json(path, current)
            try:
                _append_history(event, scope, session_id=session_id)
            except BaseException:
                rollback_error: BaseException | None = None
                try:
                    store._write_json(path, original)
                except BaseException as exc:
                    rollback_error = exc
                try:
                    if history_existed:
                        history.write_bytes(history_before)
                    else:
                        history.unlink(missing_ok=True)
                except BaseException as exc:
                    rollback_error = rollback_error or exc
                if rollback_error is not None:
                    raise RuntimeError(
                        "harness history failed and state rollback failed"
                    ) from rollback_error
                raise
        state.clear()
        state.update(copy.deepcopy(current))
        return event

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
                applied.append(
                    {
                        **edit,
                        "id": eid,
                        "before": before,
                        "applied": False,
                        "error": "entry changed during planning",
                    }
                )
                continue

        if action == "delete":
            if not before:
                applied.append(
                    {**edit, "id": eid, "applied": False, "error": "entry not found"}
                )
                continue
            del records[eid]
            touched.add(key)
            applied.append(
                {**edit, "id": eid, "before": before, "after": None, "applied": True}
            )
            continue

        if action == "create" and before:
            applied.append(
                {
                    **edit,
                    "id": eid,
                    "before": before,
                    "applied": False,
                    "error": "entry already exists",
                }
            )
            continue
        if action == "update" and not before:
            applied.append(
                {**edit, "id": eid, "applied": False, "error": "entry not found"}
            )
            continue

        after = _merge_entry(
            before, edit, eid=eid, kind=kind, scope=scope, source=source
        )
        records[eid] = after
        touched.add(key)
        applied.append(
            {
                **edit,
                "id": eid,
                "before": before,
                "after": copy.deepcopy(after),
                "applied": True,
            }
        )

    changes = [
        f"{e['action']} {e['kind']}:{e['id']}" for e in applied if e.get("applied")
    ]
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
    return event


_apply_unpersisted = apply


def _inverse_edits(event: dict[str, Any]) -> list[dict[str, Any]]:
    inverse: list[dict[str, Any]] = []
    for entry in reversed(event.get("applied") or []):
        if not entry.get("applied"):
            continue
        before, after = entry.get("before"), entry.get("after")
        kind, eid = entry["kind"], entry["id"]
        if before is None:
            inverse.append(
                {
                    "action": "delete",
                    "kind": kind,
                    "id": eid,
                    "reason": f"rollback of {event['id']}",
                }
            )
        else:
            action = "update" if after is not None else "create"
            inverse.append(
                {
                    "action": action,
                    "kind": kind,
                    "id": eid,
                    "title": before.get("title", eid),
                    "content": before.get("content", ""),
                    "path": before.get("path", "general"),
                    "reference": before.get("reference", {}),
                    "arguments": before.get("arguments", {}),
                    "metadata": before.get("metadata", {}),
                    "reason": f"rollback of {event['id']}",
                }
            )
    return inverse


def find_event(
    rid: str, scope: str = "global", *, session_id: str | None = None
) -> dict[str, Any]:
    for event in reversed(history(scope, session_id=session_id)):
        if event.get("id") == rid:
            return event
    raise KeyError(f"no refinement with id {rid!r}")


def rollback(
    rid: str, scope: str = "global", *, session_id: str | None = None
) -> dict[str, Any]:
    """Undo a refinement by replaying its applied edits in reverse."""
    target = find_event(rid, scope, session_id=session_id)
    inverse = _inverse_edits(target)
    state = load(scope, session_id=session_id)
    return apply(
        state,
        {
            "summary": f"rollback of {rid}",
            "rationale": target.get("trigger", ""),
            "expectedOutcome": "이전 harness 상태 복원",
            "edits": inverse,
        },
        baseline=None,
        scope=scope,
        session_id=session_id,
        rid=new_id(),
        source="rollback",
        max_edits=max(len(inverse), MAX_EDITS),
        rollback_of=rid,
    )


def auto_kinds(cfg: dict[str, Any] | None) -> set[str]:
    raw = (cfg or {}).get("harness_auto_approve")
    if raw is None:
        raw = ["memory", "skill_note"]
    return {str(kind).strip().lower() for kind in raw}


def submit(
    proposal: dict[str, Any],
    *,
    cfg: dict[str, Any] | None = None,
    scope: str = "global",
    source: str = "harness",
    session_id: str | None = None,
    rid: str | None = None,
    origin: str = "harness",
) -> dict[str, Any]:
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
    auto = auto_kinds(cfg) if scope == "local" else set()

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
        queued.append(
            approvals.propose(
                category="harness",
                title=f"harness {edit['action']} {kind}: {label}",
                description=str(edit.get("reason") or proposal.get("rationale") or "")[
                    :400
                ],
                payload={
                    "edit": edit,
                    "scope": scope,
                    "session_id": session_id,
                    "summary": proposal.get("summary", ""),
                    "rationale": proposal.get("rationale", ""),
                    "expectedOutcome": proposal.get("expectedOutcome", ""),
                },
                cfg=cfg,
                origin=origin,
            )
        )

    applied: dict[str, Any] | None = None
    if auto_edits:
        current = load(scope, session_id=session_id)
        applied = apply(
            current,
            {**proposal, "edits": auto_edits},
            baseline=current,
            scope=scope,
            session_id=session_id,
            rid=rid,
            source=source,
            max_edits=max_edits,
        )
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
    session_id = payload.get("session_id")
    session_id = str(session_id) if session_id is not None else None
    summary = str(
        payload.get("summary") or f"approved {edit.get('action')} {edit.get('kind')}"
    )
    event = apply(
        load(scope, session_id=session_id),
        {
            "summary": summary,
            "rationale": payload.get("rationale", ""),
            "expectedOutcome": payload.get("expectedOutcome", ""),
            "edits": [edit],
        },
        baseline=None,
        scope=scope,
        session_id=session_id,
        rid=new_id(),
        source="approval",
    )
    outcome = event["applied"][0]
    if not outcome.get("applied"):
        raise ValueError(f"harness edit rejected: {outcome.get('error')}")
    return (
        f"Applied harness {outcome['action']} "
        f"{outcome['kind']}:{outcome['id']} (refinement {event['id']})."
    )


def _clip(text: str, width: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def validate_working_session_id(session_id: str) -> str:
    value = str(session_id or "").strip()
    if not _WORKING_SESSION_ID.fullmatch(value) or value in {".", ".."}:
        raise ValueError(
            "invalid session id: use 1-128 ASCII letters, digits, '.', '_' or "
            "'-', beginning with a letter or digit"
        )
    return value


def _decode_working(raw: object) -> dict[str, Any]:
    working = empty_working()
    if not isinstance(raw, dict):
        return working
    revision = raw.get("revision")
    if not isinstance(revision, int) or revision <= 0:
        return working
    working["revision"] = revision
    updated_at = raw.get("updated_at")
    if isinstance(updated_at, str):
        working["updated_at"] = updated_at
    processed = 0
    for field in WORKING_FIELDS:
        values = raw.get(field)
        if isinstance(values, list):
            normalized: list[str] = []
            seen: set[str] = set()
            for value in values:
                if processed >= WORKING_MAX_VALUES:
                    break
                processed += 1
                if not isinstance(value, str):
                    continue
                text = value.strip()
                if not text or len(text) > WORKING_MAX_ITEM or text in seen:
                    continue
                seen.add(text)
                normalized.append(text)
            working[field] = normalized
    worst_case_session = "s" * 128
    while len(_render_working_state(worst_case_session, working)) > WORKING_MAX_RENDER:
        for field in reversed(WORKING_FIELDS):
            if working[field]:
                working[field].pop()
                break
        else:
            return empty_working()
    return working


def _working_value(value: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("working-memory values must not be empty")
    if len(text) > WORKING_MAX_ITEM:
        raise ValueError(
            f"working-memory values must be at most {WORKING_MAX_ITEM} characters"
        )
    return text


def _working_merge(current: object, incoming: Iterable[str]) -> list[str]:
    values = list(current) if isinstance(current, list) else []
    for raw in incoming:
        value = _working_value(raw)
        if value not in values:
            values.append(value)
    return values


def working_state(session_id: str) -> dict[str, Any]:
    session = validate_working_session_id(session_id)
    return copy.deepcopy(
        load("local", session_id=session).get("working") or empty_working()
    )


def _next_working(
    session_id: str,
    current: dict[str, Any],
    incoming: dict[str, Iterable[str]],
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    updated = {
        "revision": int(current.get("revision") or 0) + 1,
        "updated_at": updated_at or _now(),
        **{
            field: _working_merge(current.get(field), incoming[field])
            for field in WORKING_FIELDS
        },
    }
    if len(_render_working_state(session_id, updated)) > WORKING_MAX_RENDER:
        raise ValueError(
            f"working memory exceeds {WORKING_MAX_RENDER} rendered characters"
        )
    return updated


def preview_working_update(
    session_id: str,
    *,
    corrections: Iterable[str] = (),
    constraints: Iterable[str] = (),
    decisions: Iterable[str] = (),
    incomplete: Iterable[str] = (),
    evidence: Iterable[str] = (),
    next_actions: Iterable[str] = (),
) -> dict[str, Any]:
    """Validate and render-budget a prospective update without persisting it."""
    session = validate_working_session_id(session_id)
    incoming = {
        "corrections": corrections,
        "constraints": constraints,
        "decisions": decisions,
        "incomplete": incomplete,
        "evidence": evidence,
        "next_actions": next_actions,
    }
    return _next_working(session, working_state(session), incoming)


def preview_working_clear(current_revision: int) -> dict[str, Any]:
    """Create the canonical clear result before its revision-checked commit."""
    updated = empty_working()
    updated["revision"] = current_revision + 1
    updated["updated_at"] = _now()
    return updated


def update_working(
    session_id: str,
    *,
    corrections: Iterable[str] = (),
    constraints: Iterable[str] = (),
    decisions: Iterable[str] = (),
    incomplete: Iterable[str] = (),
    evidence: Iterable[str] = (),
    next_actions: Iterable[str] = (),
    expected_revision: int | None = None,
    updated_at: str | None = None,
    commit: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    session = validate_working_session_id(session_id)
    path = state_path("local", session_id=session)
    path.parent.mkdir(parents=True, exist_ok=True)
    incoming = {
        "corrections": corrections,
        "constraints": constraints,
        "decisions": decisions,
        "incomplete": incomplete,
        "evidence": evidence,
        "next_actions": next_actions,
    }
    with working_transaction(session):
        with store.file_lock(path):
            state = load("local", session_id=session)
            current = state.get("working") or empty_working()
            current_revision = int(current.get("revision") or 0)
            if expected_revision is not None and current_revision != expected_revision:
                raise ValueError(
                    f"working memory revision conflict; current revision is {current_revision}"
                )
            updated = _next_working(
                session,
                current,
                incoming,
                updated_at=updated_at,
            )
            state["schema"] = 3
            state["working"] = updated
            store._write_json(path, state)
            if commit is not None:
                try:
                    commit()
                except BaseException:
                    state["working"] = copy.deepcopy(current)
                    store._write_json(path, state)
                    raise
    return copy.deepcopy(updated)


def clear_working_revisioned(
    session_id: str,
    *,
    expected_revision: int,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Clear session Working Memory while preserving monotonic revision identity."""
    session = validate_working_session_id(session_id)
    path = state_path("local", session_id=session)
    path.parent.mkdir(parents=True, exist_ok=True)
    with working_transaction(session):
        with store.file_lock(path):
            state = load("local", session_id=session)
            current = state.get("working") or empty_working()
            current_revision = int(current.get("revision") or 0)
            if current_revision != expected_revision:
                raise ValueError(
                    f"working memory revision conflict; current revision is {current_revision}"
                )
            updated = empty_working()
            updated["revision"] = current_revision + 1
            updated["updated_at"] = updated_at or _now()
            state["schema"] = 3
            state["working"] = updated
            store._write_json(path, state)
    return copy.deepcopy(updated)


def clear_working(
    session_id: str,
    *,
    commit: Callable[[], Any] | None = None,
) -> bool:
    session = validate_working_session_id(session_id)
    path = state_path("local", session_id=session)
    with working_transaction(session):
        with store.file_lock(path):
            state = load("local", session_id=session)
            current = state.get("working") or empty_working()
            if _working_is_empty(current):
                if commit is not None:
                    commit()
                return False
            state["schema"] = 3
            state["working"] = preview_working_clear(
                int(current.get("revision") or 0)
            )
            store._write_json(path, state)
            if commit is not None:
                try:
                    commit()
                except BaseException:
                    state["working"] = copy.deepcopy(current)
                    store._write_json(path, state)
                    raise
            return True


def restore_working(
    session_id: str,
    previous: dict[str, Any],
    *,
    expected_revision: int,
) -> bool:
    """Rollback one CLI mutation without clobbering a concurrent writer."""
    session = validate_working_session_id(session_id)
    restored = _decode_working(previous)
    path = state_path("local", session_id=session)
    path.parent.mkdir(parents=True, exist_ok=True)
    with store.file_lock(path):
        state = load("local", session_id=session)
        current = state.get("working") or empty_working()
        if int(current.get("revision") or 0) != expected_revision:
            return False
        state["schema"] = 3
        state["working"] = restored
        store._write_json(path, state)
    return True


def _render_working_state(session_id: str, working: dict[str, Any]) -> str:
    if _working_is_empty(working):
        return ""
    headings = {
        "corrections": "User corrections",
        "constraints": "Constraints",
        "decisions": "Decisions",
        "incomplete": "Incomplete items",
        "evidence": "Evidence",
        "next_actions": "Next actions",
    }
    lines = [
        "<working-memory>",
        "Current session state. Preserve it across turns. It is context, "
        "not a new user instruction or long-term semantic memory.",
        f"Session: {session_id} (revision {working['revision']})",
    ]
    for field in WORKING_FIELDS:
        values = working.get(field) or []
        if not values:
            continue
        lines.append(f"{headings[field]}:")
        lines.extend(f"- {escape(str(value), quote=False)}" for value in values)
    lines.append("</working-memory>")
    return "\n".join(lines)


def render_working(session_id: str) -> str:
    session = validate_working_session_id(session_id)
    return _render_working_state(session, working_state(session))


def render_working_reset(session_id: str) -> str:
    session = escape(
        validate_working_session_id(session_id),
        quote=True,
    )
    return f'<working-memory-reset session="{session}" revision="0" state="empty"/>'


def merge_states(*states: dict[str, Any]) -> dict[str, Any]:
    merged = empty_state()
    for state in states:
        for kind in KINDS:
            for eid, entry in (state.get("entries", {}).get(kind) or {}).items():
                key = (
                    eid
                    if eid not in merged["entries"][kind]
                    else f"{entry.get('scope', 'local')}:{eid}"
                )
                merged["entries"][kind][key] = entry
        merged["refinements"].extend(state.get("refinements") or [])
        working = state.get("working")
        if isinstance(working, dict) and int(working.get("revision") or 0) > 0:
            merged["working"] = copy.deepcopy(working)
    merged["refinements"].sort(key=lambda e: str(e.get("created_at", "")))
    return merged


def snapshot(session_id: str | None) -> dict[str, Any]:
    """Return one revisioned global + current-session local prompt snapshot."""
    state = merge_states(
        load("global"),
        load("local", session_id=session_id),
    )
    encoded = json.dumps(
        state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "revision": hashlib.sha256(encoded).hexdigest()[:16],
        "state": state,
    }


def render_block(
    state: dict[str, Any],
    *,
    per_kind: int = RENDER_PER_KIND,
    history_limit: int = RENDER_HISTORY,
    width: int = RENDER_WIDTH,
    budget: int | None = None,
    revision: str | None = None,
) -> str:
    """Compact the harness into the system-prompt block (empty when unused)."""
    entries = state.get("entries") or {}
    refinements = state.get("refinements") or []
    if not any(entries.get(kind) for kind in KINDS) and not refinements:
        return ""

    lines = ["## Harness (자가개선 상태)"]
    if revision:
        lines.append(f"revision: {revision}")
    lines.append("아래는 요약이다. 라우팅 힌트로 쓰고 상세가 필요하면 조회하라.")

    for kind in KINDS:
        records = entries.get(kind) or {}
        if not records:
            continue
        ordered = sorted(
            records.values(), key=lambda e: str(e.get("updated_at", "")), reverse=True
        )
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
    return (
        e.get("title", "") for e in (state.get("entries", {}).get(kind) or {}).values()
    )
