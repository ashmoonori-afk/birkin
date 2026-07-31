"""Proactive follow-through — user-confirmed commitments and scheduled check-ins.

Birkin remembers a commitment the user explicitly confirmed, asks about it at the
agreed time, records the answer, and captures the next action. The LLM may
propose a *candidate*; only the functions in this module create, schedule,
transition, or close one, so a model cannot silently change user state.

State lives under ``~/.birkin/companion/``:

- ``state.json``   — contexts, commitments, notification policy, send ledger.
- ``events.jsonl`` — append-only domain transitions (no conversation bodies).

Both are written through :func:`store._write_json` (atomic rename) under
:class:`store.file_lock`, because the gateway (callback taps) and the scheduler
daemon (check-in sends) mutate them from separate processes.

Timezones: the IANA name is stored and resolved through :mod:`zoneinfo` when the
OS ships a tz database. Windows without ``tzdata`` has none (``TZPATH == ()``),
so the fixed UTC offset captured at activation is the documented fallback — the
zero-runtime-dependency rule (see pyproject) rules out vendoring the database.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any

from . import config, store

_STATE_VERSION = 1

# candidate -> active -> blocked | snoozed | done | stopped.
# ``done`` and ``stopped`` are terminal: no outgoing edge, so a closed
# commitment cannot be reopened without an explicit new one.
_TRANSITIONS: dict[str, frozenset[str]] = {
    "candidate": frozenset({"active", "stopped"}),
    "active": frozenset({"done", "blocked", "snoozed", "stopped"}),
    "blocked": frozenset({"active", "done", "snoozed", "stopped"}),
    "snoozed": frozenset({"active", "done", "blocked", "stopped"}),
    "done": frozenset(),
    "stopped": frozenset(),
}
# Statuses a reschedule may move: an open commitment only. A terminal one, and
# an unconfirmed candidate, must go through activate() instead.
_RESCHEDULABLE = frozenset({"active", "blocked", "snoozed"})
ACTIONS = ("done", "blocked", "snooze", "stop", "wrong")
_ACTION_STATUS = {"done": "done", "blocked": "blocked", "snooze": "snoozed",
                  "stop": "stopped", "wrong": "stopped"}

# Inferred affect is turn-local: it may shape one reply, never persistent state
# and never a reason to contact the user. Rejected on the event write path.
_AFFECT_KEYS = frozenset({"emotion", "affect", "mood", "sentiment", "feeling"})

# A check-in that went unanswered this long is expired — it is NOT delivered
# later as a morning backlog unless the user turns catch-up on.
_EXPIRY_MINUTES = 360
# Consecutive ignored check-ins after which Birkin stops asking on its own.
_IGNORED_LIMIT = 3
_SEND_LEDGER_CAP = 200
_SUMMARY_CAP = 200


class CompanionError(ValueError):
    """An invalid domain request (bad transition, unknown id, denied context)."""


# -- time ------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def parse_iso(value: Any) -> datetime | None:
    """Parse a stored timestamp. A naive value is read as UTC, never as local:
    the daemon and the gateway can run under different TZ environments."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def resolve_tz(name: str, offset_minutes: int | None = None) -> tzinfo:
    """The tzinfo for an IANA ``name``, falling back to a fixed offset.

    ``zoneinfo`` honours DST where the OS provides the tz database. Where it does
    not (Windows without ``tzdata``), the offset captured at activation keeps
    check-in times stable and explicit instead of silently sliding to UTC.
    """
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(str(name))
    except Exception:
        return timezone(timedelta(minutes=int(offset_minutes or 0)))


def tz_available() -> bool:
    """Whether this interpreter can resolve IANA names (DST-aware behavior).

    Probes a DST-observing zone, not ``UTC``: ``ZoneInfo("UTC")`` succeeds from a
    built-in fallback even with no tz database installed, so it would report
    True on a machine that cannot resolve a real zone at all.
    """
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("America/New_York")
        return True
    except Exception:
        return False


def _policy_tz(policy: dict[str, Any]) -> tzinfo:
    return resolve_tz(policy.get("timezone", "UTC"),
                      policy.get("utc_offset_minutes"))


def _clock(text: str) -> tuple[int, int] | None:
    raw = str(text or "").strip()
    if len(raw) != 5 or raw[2] != ":":
        return None
    hh, mm = raw[:2], raw[3:]
    if not (hh.isdecimal() and mm.isdecimal()):
        return None
    hour, minute = int(hh), int(mm)
    return (hour, minute) if hour <= 23 and minute <= 59 else None


# -- state io --------------------------------------------------------------

def default_policy() -> dict[str, Any]:
    """Proactive contact is opt-in: ``enabled`` defaults to False."""
    return {"enabled": False, "timezone": "UTC", "utc_offset_minutes": 0,
            "quiet_hours": {"start": "22:00", "end": "08:00"},
            "daily_cap": 1, "cooldown_minutes": 720, "catch_up": False,
            "expiry_minutes": _EXPIRY_MINUTES, "version": 1}


def _blank_state() -> dict[str, Any]:
    return {"version": _STATE_VERSION, "contexts": {}, "commitments": {},
            "policy": default_policy(), "sends": []}


def load_state() -> dict[str, Any]:
    """The whole domain state, with any missing section defaulted."""
    raw = store._read_json(config.companion_state_path(), None)
    state = raw if isinstance(raw, dict) else {}
    blank = _blank_state()
    for key, fallback in blank.items():
        value = state.get(key)
        if not isinstance(value, type(fallback)):
            state[key] = fallback
    policy = default_policy()
    policy.update({k: v for k, v in state["policy"].items() if k in policy})
    state["policy"] = policy
    return state


def _save_state(state: dict[str, Any]) -> None:
    state["version"] = _STATE_VERSION
    sends = state.get("sends") or []
    state["sends"] = sends[-_SEND_LEDGER_CAP:]
    store._write_json(config.companion_state_path(), state)


def _lock() -> store.file_lock:
    return store.file_lock(config.companion_state_path())


# -- events ----------------------------------------------------------------

def append_event(*, kind: str, context_id: str, commitment_id: str = "",
                 actor: str = "system", summary: str = "",
                 source_ref: str = "", data: dict[str, Any] | None = None,
                 now: datetime | None = None) -> dict[str, Any]:
    """Append one domain transition. Raises on an attempt to persist affect.

    The guard is here rather than at the call sites because this is the only
    durable write path for domain narrative — an inferred mood must not reach it
    from any caller, present or future.
    """
    payload = dict(data or {})
    offending = _AFFECT_KEYS.intersection({str(k).lower() for k in payload})
    if offending:
        raise CompanionError(
            f"inferred affect is turn-local and cannot be stored: "
            f"{sorted(offending)}")
    event = {"id": uuid.uuid4().hex[:12], "at": _iso(now or _utcnow()),
             "type": str(kind), "context_id": str(context_id),
             "commitment_id": str(commitment_id), "actor": str(actor),
             "summary": str(summary)[:_SUMMARY_CAP],
             "source_ref": str(source_ref), "data": payload}
    try:
        with config.companion_events_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        pass  # the ledger must never break a check-in or a callback
    return event


def read_events(limit: int = 50, *, commitment_id: str = "") -> list[dict[str, Any]]:
    """Recent events, newest last. The timeline is derived from these."""
    path = config.companion_events_path()
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if commitment_id and event.get("commitment_id") != commitment_id:
            continue
        out.append(event)
    return out[-limit:] if limit > 0 else []


# -- contexts --------------------------------------------------------------

def is_private_chat(context_id: str) -> bool:
    """Telegram group/channel ids are negative; the MVP is private chats only.

    Enforced in storage, not in prompt prose, so no model output can widen it.
    """
    channel, _, chat = str(context_id).partition(":")
    return bool(chat) and channel == "telegram" and not chat.startswith("-")


def bind_context(context_id: str, *, owner_id: str,
                 now: datetime | None = None) -> dict[str, Any]:
    """Register the one trusted private chat that may receive check-ins."""
    if not is_private_chat(context_id):
        raise CompanionError(
            f"only telegram private chats are supported: {context_id!r}")
    with _lock():
        state = load_state()
        record = {"id": str(context_id), "kind": "private_chat",
                  "owner_id": str(owner_id), "memory_mode": "explicit_only",
                  "proactive_mode": "on", "state": "active",
                  "bound_at": _iso(now or _utcnow())}
        state["contexts"][str(context_id)] = record
        _save_state(state)
    append_event(kind="context_bound", context_id=context_id, actor="user",
                 summary="Bound private chat for follow-through", now=now)
    return record


def get_context(context_id: str) -> dict[str, Any] | None:
    return load_state()["contexts"].get(str(context_id))


# -- policy ----------------------------------------------------------------

def get_policy() -> dict[str, Any]:
    return load_state()["policy"]


def set_policy(**changes: Any) -> dict[str, Any]:
    """Update the notification policy and bump its version.

    A commitment scheduled under an older version has its pending send cancelled
    at claim time (see :func:`eligible`), so a policy edit can never let a
    message go out under rules the user has already replaced.
    """
    allowed = set(default_policy()) - {"version"}
    unknown = set(changes) - allowed
    if unknown:
        raise CompanionError(f"unknown policy keys: {sorted(unknown)}")
    for key in ("quiet_hours",):
        if key in changes and changes[key] is not None:
            window = changes[key]
            if not isinstance(window, dict) or _clock(window.get("start")) is None \
                    or _clock(window.get("end")) is None:
                raise CompanionError("quiet_hours needs HH:MM start and end")
    for key in ("daily_cap", "cooldown_minutes", "expiry_minutes"):
        if key in changes:
            try:
                changes[key] = max(0, int(changes[key]))
            except (TypeError, ValueError):
                raise CompanionError(f"{key} must be an integer") from None
    with _lock():
        state = load_state()
        policy = state["policy"]
        policy.update(changes)
        policy["version"] = int(policy.get("version", 1)) + 1
        state["policy"] = policy
        _save_state(state)
    append_event(kind="policy_changed", context_id="", actor="user",
                 summary=f"Policy updated to version {policy['version']}",
                 data={"keys": sorted(changes)})
    return policy


def pause_all() -> dict[str, Any]:
    """``/checkin pause`` — takes effect before any later send or model call."""
    return set_policy(enabled=False)


def resume() -> dict[str, Any]:
    return set_policy(enabled=True)


# -- commitments -----------------------------------------------------------

def add_candidate(*, context_id: str, outcome: str, source_ref: str,
                  next_action: str = "",
                  now: datetime | None = None) -> dict[str, Any]:
    """Record an extracted candidate. It cannot notify until :func:`activate`."""
    if not str(outcome).strip():
        raise CompanionError("a commitment needs an outcome")
    if not str(source_ref).strip():
        raise CompanionError("a commitment needs a source reference")
    if not is_private_chat(context_id):
        raise CompanionError(f"unsupported context: {context_id!r}")
    moment = now or _utcnow()
    record = {
        "id": uuid.uuid4().hex[:12], "context_id": str(context_id),
        "outcome": str(outcome).strip(), "next_action": str(next_action).strip(),
        "status": "candidate", "source_ref": str(source_ref).strip(),
        "check_in_at": None, "timezone": None, "utc_offset_minutes": None,
        "revision": 1, "created_at": _iso(moment), "updated_at": _iso(moment),
        "policy_version": None, "checkin": None, "ignored_streak": 0,
    }
    with _lock():
        state = load_state()
        state["commitments"][record["id"]] = record
        _save_state(state)
    append_event(kind="commitment_proposed", context_id=context_id,
                 commitment_id=record["id"], actor="assistant",
                 summary=f"Candidate: {record['outcome']}",
                 source_ref=record["source_ref"], now=moment)
    return record


def activate(commitment_id: str, *, check_in_at: str, tz_name: str = "UTC",
             utc_offset_minutes: int | None = None,
             now: datetime | None = None) -> dict[str, Any]:
    """Confirm a candidate: the user chose the outcome and the check-in time.

    One active commitment per context (MVP), so a confirmation cannot quietly
    queue a second stream of check-ins.
    """
    when = parse_iso(check_in_at)
    if when is None:
        raise CompanionError(f"unparseable check-in time: {check_in_at!r}")
    if utc_offset_minutes is None:
        offset = when.utcoffset()
        utc_offset_minutes = int(offset.total_seconds() // 60) if offset else 0
    moment = now or _utcnow()
    with _lock():
        state = load_state()
        record = _require(state, commitment_id)
        _check_transition(record["status"], "active")
        context = state["contexts"].get(record["context_id"])
        if not context or context.get("state") != "active":
            raise CompanionError("context is not bound and active")
        clash = [
            other for other in state["commitments"].values()
            if other["context_id"] == record["context_id"]
            and other["id"] != record["id"] and other["status"] == "active"
        ]
        if clash:
            raise CompanionError(
                f"context already has an active commitment: {clash[0]['id']}")
        record.update({"status": "active", "check_in_at": _iso(when),
                       "timezone": str(tz_name),
                       "utc_offset_minutes": int(utc_offset_minutes),
                       "policy_version": int(state["policy"].get("version", 1)),
                       "updated_at": _iso(moment), "checkin": None})
        _save_state(state)
    append_event(kind="commitment_activated", context_id=record["context_id"],
                 commitment_id=record["id"], actor="user",
                 summary=f"Active: {record['outcome']}",
                 source_ref=record["source_ref"],
                 data={"check_in_at": record["check_in_at"]}, now=moment)
    return record


def get_commitment(commitment_id: str) -> dict[str, Any] | None:
    return load_state()["commitments"].get(str(commitment_id))


def list_commitments(*, context_id: str = "",
                     status: str = "") -> list[dict[str, Any]]:
    records = list(load_state()["commitments"].values())
    if context_id:
        records = [r for r in records if r["context_id"] == str(context_id)]
    if status:
        records = [r for r in records if r["status"] == str(status)]
    return sorted(records, key=lambda r: r["created_at"])


def _require(state: dict[str, Any], commitment_id: str) -> dict[str, Any]:
    record = state["commitments"].get(str(commitment_id))
    if record is None:
        raise CompanionError(f"no such commitment: {commitment_id!r}")
    return record


def _check_transition(current: str, target: str) -> None:
    if target not in _TRANSITIONS.get(current, frozenset()):
        raise CompanionError(f"invalid transition {current} -> {target}")


def correct(commitment_id: str, *, outcome: str = "", next_action: str = "",
            now: datetime | None = None) -> dict[str, Any]:
    """Apply a user correction as a new revision, preserving provenance.

    The previous values are recorded in the event, not overwritten in place, so
    ``Wrong`` at a check-in never destroys what Birkin originally believed.
    """
    moment = now or _utcnow()
    with _lock():
        state = load_state()
        record = _require(state, commitment_id)
        before = {"outcome": record["outcome"],
                  "next_action": record["next_action"],
                  "revision": record["revision"]}
        if outcome.strip():
            record["outcome"] = outcome.strip()
        if next_action.strip():
            record["next_action"] = next_action.strip()
        record["revision"] = int(record["revision"]) + 1
        record["updated_at"] = _iso(moment)
        _save_state(state)
    append_event(kind="commitment_corrected", context_id=record["context_id"],
                 commitment_id=record["id"], actor="user",
                 summary=f"Revision {record['revision']}: {record['outcome']}",
                 source_ref=record["source_ref"], data={"previous": before},
                 now=moment)
    return record


def delete_commitment(commitment_id: str,
                      now: datetime | None = None) -> bool:
    """Remove a commitment from retrieval and cancel any scheduled check-in.

    Deletion is immediate: the record is gone from ``state.json`` before this
    returns, so a send claimed afterwards finds nothing to deliver.
    """
    with _lock():
        state = load_state()
        record = state["commitments"].pop(str(commitment_id), None)
        if record is None:
            return False
        state["sends"] = [s for s in state.get("sends", [])
                          if s.get("commitment_id") != str(commitment_id)]
        _save_state(state)
    append_event(kind="commitment_deleted", context_id=record["context_id"],
                 commitment_id=str(commitment_id), actor="user",
                 summary="Commitment and its check-in were deleted", now=now)
    return True


# -- check-in scheduling ---------------------------------------------------

def checkin_key(record: dict[str, Any]) -> str:
    """One dedupe key per (commitment, check-in time) — one delivery per key."""
    return f"{record['id']}:{record.get('check_in_at') or ''}"


def _in_quiet_hours(policy: dict[str, Any], moment: datetime) -> bool:
    window = policy.get("quiet_hours") or {}
    start, end = _clock(window.get("start")), _clock(window.get("end"))
    if start is None or end is None:
        return False
    local = moment.astimezone(_policy_tz(policy))
    current = (local.hour, local.minute)
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end   # window crosses midnight


def _sends_today(state: dict[str, Any], moment: datetime) -> int:
    policy = state["policy"]
    today = moment.astimezone(_policy_tz(policy)).date()
    total = 0
    for send in state.get("sends", []):
        at = parse_iso(send.get("at"))
        if at is not None and at.astimezone(_policy_tz(policy)).date() == today:
            total += 1
    return total


def _last_send(state: dict[str, Any]) -> datetime | None:
    stamps = [parse_iso(s.get("at")) for s in state.get("sends", [])]
    real = [s for s in stamps if s is not None]
    return max(real) if real else None


def eligible(state: dict[str, Any], record: dict[str, Any],
             now: datetime | None = None) -> tuple[bool, str]:
    """Whether a check-in for ``record`` may be sent right now, and why not.

    Good silence is the default: every branch here is a reason Birkin stays
    quiet. Re-evaluated at send time, not only at schedule time.
    """
    moment = now or _utcnow()
    policy = state["policy"]
    if not policy.get("enabled"):
        return False, "proactive contact is off"
    if record["status"] != "active":
        return False, f"commitment is {record['status']}"
    if not str(record.get("source_ref") or "").strip():
        return False, "commitment has no source reference"
    context = state["contexts"].get(record["context_id"])
    if not context or context.get("state") != "active":
        return False, "context is not active"
    if context.get("proactive_mode") != "on":
        return False, "context has proactive mode off"
    if not is_private_chat(record["context_id"]):
        return False, "context is not a private chat"
    if int(record.get("policy_version") or 0) != int(policy.get("version", 1)):
        return False, "policy changed after scheduling"
    when = parse_iso(record.get("check_in_at"))
    if when is None:
        return False, "no check-in time"
    if moment < when:
        return False, "not due yet"
    expiry = int(policy.get("expiry_minutes", _EXPIRY_MINUTES))
    if expiry and moment > when + timedelta(minutes=expiry) \
            and not policy.get("catch_up"):
        return False, "check-in expired"
    open_checkin = record.get("checkin") or {}
    if open_checkin and not open_checkin.get("answered_at"):
        return False, "previous check-in is still open"
    if int(record.get("ignored_streak") or 0) >= _IGNORED_LIMIT:
        return False, "recent check-ins were ignored"
    if _in_quiet_hours(policy, moment):
        return False, "inside quiet hours"
    cap = int(policy.get("daily_cap", 1))
    if cap and _sends_today(state, moment) >= cap:
        return False, "daily cap reached"
    cooldown = int(policy.get("cooldown_minutes", 0))
    last = _last_send(state)
    if cooldown and last is not None \
            and moment < last + timedelta(minutes=cooldown):
        return False, "inside cooldown"
    key = checkin_key(record)
    if any(s.get("key") == key for s in state.get("sends", [])):
        return False, "already sent for this check-in"
    return True, "eligible"


def due_checkins(now: datetime | None = None) -> list[dict[str, Any]]:
    """Active commitments whose check-in time has come round."""
    moment = now or _utcnow()
    state = load_state()
    out = []
    for record in state["commitments"].values():
        if record["status"] != "active":
            continue
        when = parse_iso(record.get("check_in_at"))
        if when is not None and when <= moment:
            out.append(record)
    return sorted(out, key=lambda r: str(r.get("check_in_at")))


def claim_checkin(commitment_id: str,
                  now: datetime | None = None) -> tuple[bool, str]:
    """Atomically claim the right to send one check-in.

    Returns ``(True, dedupe_key)`` for the single caller that won, else
    ``(False, reason)``. The claim is recorded *before* the network send, which
    is what makes delivery at-most-once across two daemons and across a restart
    — the same trade cron.claim_if_due already documents: for a nudge, asking
    twice is worse than not asking.

    A stale ``policy_version`` cancels this send and re-stamps the commitment, so
    the next poll re-evaluates it under the policy the user actually has now.
    """
    moment = now or _utcnow()
    try:
        with _lock():
            state = load_state()
            record = state["commitments"].get(str(commitment_id))
            if record is None:
                return False, "no such commitment"
            ok, reason = eligible(state, record, moment)
            if not ok:
                if reason == "policy changed after scheduling":
                    record["policy_version"] = int(
                        state["policy"].get("version", 1))
                    record["updated_at"] = _iso(moment)
                    _save_state(state)
                elif reason == "previous check-in is still open":
                    _expire_open_checkin(state, record, moment)
                    _save_state(state)
                return False, reason
            key = checkin_key(record)
            state.setdefault("sends", []).append(
                {"key": key, "at": _iso(moment),
                 "context_id": record["context_id"],
                 "commitment_id": record["id"]})
            record["checkin"] = {"key": key, "sent_at": _iso(moment),
                                 "message_id": "", "answered_at": None,
                                 "answer": ""}
            record["updated_at"] = _iso(moment)
            _save_state(state)
    except store.FileLockTimeout:
        return False, "state is busy"
    append_event(kind="checkin_sent", context_id=record["context_id"],
                 commitment_id=record["id"], actor="system",
                 summary=f"Asked about: {record['outcome']}",
                 source_ref=record["source_ref"], data={"key": key},
                 now=moment)
    return True, key


def _expire_open_checkin(state: dict[str, Any], record: dict[str, Any],
                         moment: datetime) -> None:
    """Age out an unanswered check-in and count it against the ignored streak."""
    open_checkin = record.get("checkin") or {}
    sent = parse_iso(open_checkin.get("sent_at"))
    expiry = int(state["policy"].get("expiry_minutes", _EXPIRY_MINUTES))
    if sent is None or not expiry or moment <= sent + timedelta(minutes=expiry):
        return
    record["checkin"] = None
    record["ignored_streak"] = int(record.get("ignored_streak") or 0) + 1
    record["updated_at"] = _iso(moment)


def record_delivery(commitment_id: str, message_id: str) -> None:
    """Retain the Telegram ``message_id`` so the receipt can edit in place."""
    with _lock():
        state = load_state()
        record = state["commitments"].get(str(commitment_id))
        if record is None or not record.get("checkin"):
            return
        record["checkin"]["message_id"] = str(message_id)
        _save_state(state)


# -- answering a check-in --------------------------------------------------

def answer(commitment_id: str, action: str, *, source_ref: str = "",
           next_action: str = "", snooze_minutes: int = 60,
           now: datetime | None = None) -> dict[str, Any]:
    """Apply one check-in answer. Idempotent for a repeated identical tap.

    Telegram re-delivers a callback when the ACK is lost, so a second tap of the
    same button must not double-transition. The stored answer is compared first;
    a *different* action after an answer is refused rather than applied.
    """
    verb = str(action).strip().lower()
    if verb not in ACTIONS:
        raise CompanionError(f"unknown action: {action!r}")
    moment = now or _utcnow()
    with _lock():
        state = load_state()
        record = _require(state, commitment_id)
        open_checkin = record.get("checkin") or {}
        if open_checkin.get("answered_at"):
            if open_checkin.get("answer") == verb:
                return {"ok": True, "repeat": True, "status": record["status"],
                        "commitment": record,
                        "message": _receipt(record, verb, repeat=True)}
            raise CompanionError(
                f"this check-in was already answered with "
                f"{open_checkin.get('answer')!r}")
        target = _ACTION_STATUS[verb]
        _check_transition(record["status"], target)
        # Keyed before the mutation below: a snooze moves check_in_at, and the
        # marker has to identify the check-in that was actually answered.
        answered_key = open_checkin.get("key") or checkin_key(record)
        record["status"] = target
        record["updated_at"] = _iso(moment)
        record["ignored_streak"] = 0
        if verb == "snooze":
            minutes = max(1, int(snooze_minutes or 60))
            record["check_in_at"] = _iso(moment + timedelta(minutes=minutes))
        if verb == "wrong":
            record["wrong"] = True
        if next_action.strip():
            record["next_action"] = next_action.strip()
        # Written even when no send claimed a check-in (the CLI answers
        # directly), because this marker is what makes a repeated tap
        # idempotent rather than an invalid second transition.
        record["checkin"] = {**open_checkin, "key": answered_key,
                             "answered_at": _iso(moment), "answer": verb}
        _save_state(state)
    append_event(kind="checkin_answered", context_id=record["context_id"],
                 commitment_id=record["id"], actor="user",
                 summary=f"User answered {verb}: {record['outcome']}",
                 source_ref=source_ref or record["source_ref"],
                 data={"action": verb, "status": record["status"]}, now=moment)
    return {"ok": True, "repeat": False, "status": record["status"],
            "commitment": record, "message": _receipt(record, verb)}


def reschedule(commitment_id: str, *, check_in_at: str,
               now: datetime | None = None) -> dict[str, Any]:
    """Move an open commitment to a new check-in time.

    Requires an explicit time from the user — Birkin never picks a new cadence
    for itself. Accepts ``active`` too (moving a pending check-in later is a
    reschedule, not a state change), which ``_TRANSITIONS`` cannot express
    because it only describes *status* edges.
    """
    when = parse_iso(check_in_at)
    if when is None:
        raise CompanionError(f"unparseable check-in time: {check_in_at!r}")
    moment = now or _utcnow()
    with _lock():
        state = load_state()
        record = _require(state, commitment_id)
        if record["status"] not in _RESCHEDULABLE:
            raise CompanionError(
                f"invalid transition {record['status']} -> active")
        record.update({"status": "active", "check_in_at": _iso(when),
                       "policy_version": int(state["policy"].get("version", 1)),
                       "checkin": None, "updated_at": _iso(moment)})
        _save_state(state)
    append_event(kind="checkin_rescheduled", context_id=record["context_id"],
                 commitment_id=record["id"], actor="user",
                 summary=f"Next check-in {record['check_in_at']}",
                 source_ref=record["source_ref"], now=moment)
    return record


def _receipt(record: dict[str, Any], verb: str, *, repeat: bool = False) -> str:
    """The completion receipt shown after an answer."""
    head = {
        "done": f"✅ 완료로 기록했어요: {record['outcome']}",
        "blocked": f"🚧 막힌 상태로 기록했어요: {record['outcome']}",
        "snooze": f"⏰ 다시 물어볼게요: {record.get('check_in_at') or '-'}",
        "stop": f"🛑 더 이상 묻지 않을게요: {record['outcome']}",
        "wrong": "🙏 잘못 기억했네요. 이 체크인은 멈추고 정정 내용을 기다릴게요.",
    }[verb]
    if repeat:
        head += " (이미 처리된 응답이에요)"
    if verb in ("done", "blocked") and record.get("next_action"):
        head += f"\n다음 할 일: {record['next_action']}"
    return head


def checkin_text(record: dict[str, Any]) -> str:
    """The check-in body. Always names the commitment it is asking about."""
    lines = [f"어제 확인해 달라고 하신 일이에요: {record['outcome']}"]
    if record.get("next_action"):
        lines.append(f"다음 할 일: {record['next_action']}")
    lines.append("")
    lines.append("진행됐나요?")
    return "\n".join(lines)


def why_message(record: dict[str, Any]) -> str:
    """The ``Why this message`` disclosure required on every proactive send."""
    return (f"이 메시지는 당신이 직접 확인한 약속 때문에 보냈어요.\n"
            f"· 약속: {record['outcome']}\n"
            f"· 출처: {record.get('source_ref') or '-'}\n"
            f"· 예정 시각: {record.get('check_in_at') or '-'}")


# -- natural-language entry (model proposes, the approval queue disposes) ---

def active_context_id() -> str:
    """The single active bound context, or "" (ambiguous / none)."""
    contexts = load_state()["contexts"]
    active = [cid for cid, c in contexts.items() if c.get("state") == "active"]
    return active[0] if len(active) == 1 else ""


def propose_checkin(*, outcome: str, check_in_at: str,
                    cfg: dict[str, Any], next_action: str = "",
                    context_id: str = "", origin: str = "chat",
                    now: datetime | None = None) -> dict[str, Any]:
    """Record a candidate and queue its activation for the user's approval.

    This is the ONLY entry a model gets: it cannot activate, so nothing is
    scheduled — and nothing can ever be sent — until a human approves the
    pending record (``birkin review`` / the gateway buttons), or the user has
    opted ``companion`` into ``auto_approve``.
    """
    policy = get_policy()
    if not policy.get("enabled"):
        raise CompanionError(
            "proactive check-ins are disabled — "
            "run `birkin companion policy --enable` first")
    ctx_id = str(context_id).strip() or active_context_id()
    if not ctx_id:
        raise CompanionError(
            "no bound context — run `birkin companion bind telegram:<chat-id>`"
            " (or pass context_id when several are bound)")
    when = parse_iso(check_in_at)
    if when is None:
        raise CompanionError(f"unparseable check-in time: {check_in_at!r}")
    moment = now or _utcnow()
    candidate = add_candidate(context_id=ctx_id, outcome=outcome,
                              source_ref=f"{origin}:{_iso(moment)}",
                              next_action=next_action, now=moment)
    from . import approvals  # local: approvals imports back for the executor
    offset = when.utcoffset()
    status = approvals.propose(
        category="companion",
        title=f"check-in: {candidate['outcome'][:60]}",
        description=(f"Ask about it at {check_in_at} in {ctx_id}. "
                     f"Next action: {candidate['next_action'] or '-'}"),
        payload={"commitment_id": candidate["id"],
                 "check_in_at": check_in_at,
                 "tz_name": str(policy.get("timezone", "UTC")),
                 "utc_offset_minutes": (int(offset.total_seconds() // 60)
                                        if offset else None)},
        cfg=cfg, origin=origin)
    return {**status, "commitment_id": candidate["id"]}


def apply_proposal(payload: dict[str, Any]) -> str:
    """Carry out an approved check-in proposal. Returns a human summary.
    Used by ``approvals.execute_action(category="companion")``."""
    cid = str((payload or {}).get("commitment_id", "")).strip()
    if not cid:
        raise CompanionError("companion proposal missing commitment_id")
    try:  # model/user payload may carry a non-int offset
        offset = int(payload.get("utc_offset_minutes"))
    except (TypeError, ValueError):
        offset = None
    record = activate(cid, check_in_at=str(payload.get("check_in_at", "")),
                      tz_name=str(payload.get("tz_name") or "UTC"),
                      utc_offset_minutes=offset)
    return (f"Check-in scheduled: {record['outcome']!r} at "
            f"{record['check_in_at']} in {record['context_id']}.")
