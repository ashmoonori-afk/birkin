"""Lightweight cron jobs (portable, file-based).

A job's action is either a ``prompt`` (handed to a one-off agent) or a ``shell``
command, stored in ``~/.birkin/cron.json`` and fired by the :mod:`scheduler`.

Schedules come in four shapes, all parsed by :func:`parse_schedule`:

===============  ==================================  ========================
kind             examples                            meaning
===============  ==================================  ========================
``daily``        ``09:00``, ``매일 09:00``            every day at that time
``interval``     ``every 30m``, ``30분마다``           repeating, from last run
``once``         ``2h``, ``30분 후``, ISO timestamp    fires a single time
``cron``         ``0 9 * * 1``, ``매주 월요일 09:00``    5-field cron expression
                 ``0 9 * * MON``, ``@daily``           names, Sunday-as-7, macros
===============  ==================================  ========================

Jobs written before this grammar existed carry a bare ``hour``/``minute`` and
no ``schedule`` key; those keep running through the original daily code path
untouched, so an existing ``cron.json`` neither double-fires nor goes silent.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Optional

from . import config, cronexpr, store

# The scheduler polls every 30s, so anything under a minute cannot be honored.
_MIN_INTERVAL_MINUTES = 1
# Bound on the cron-expression search. A 5-field expression that matches
# nothing (Feb 30th) would otherwise scan forever.
_CRON_SEARCH_DAYS = 366

_DURATION_RE = re.compile(r"^(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|"
                          r"hours|d|day|days|분|시간|일)$", re.I)
# Korean weekday -> cron day-of-week. '월'/'월요일' both accepted (the '요일'
# suffix is stripped before lookup).
_KO_WEEKDAYS = {"일": 0, "월": 1, "화": 2, "수": 3,
                "목": 4, "금": 5, "토": 6}
_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


# -- schedule grammar ------------------------------------------------------

def parse_duration(text: str) -> Optional[int]:
    """``"30m"`` / ``"2h"`` / ``"1d"`` -> minutes. None when unparseable."""
    m = _DURATION_RE.match(text.strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit.startswith("d") or unit == "일":
        return n * 1440
    if unit.startswith("h") or unit == "시간":
        return n * 60
    return n


def _ko_clock(text: str, build) -> Optional[dict[str, Any]]:
    """Shared 'HH:MM or reject' step for the Korean 매일/매주 forms."""
    m = _CLOCK_RE.match(text)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    return build(hour, minute)


def parse_schedule(text: str) -> Optional[dict[str, Any]]:
    """Parse a schedule expression into a stored schedule dict.

    Returns None when ``text`` is not a schedule, which lets callers try it
    speculatively against the front of a command and fall through.
    """
    text = (text or "").strip()
    if not text:
        return None

    # '30분 후' means the same as '30분'; normalize the suffix away and let the
    # duration -> one-shot path below handle it.
    if text.endswith("후"):
        text = text[:-1].strip()

    if text.startswith("매일"):
        return _ko_clock(text[2:].strip(), lambda h, m: {
            "kind": "daily", "hour": h, "minute": m,
            "display": f"매일 {h:02d}:{m:02d}"})
    if text.startswith("매주"):
        parts = text[2:].split()
        if len(parts) != 2:
            return None
        dow = _KO_WEEKDAYS.get(parts[0].removesuffix("요일"))
        if dow is None:
            return None
        return _ko_clock(parts[1], lambda h, m: {
            "kind": "cron", "expr": f"{m} {h} * * {dow}",
            "display": f"매주 {parts[0]} {h:02d}:{m:02d}"})
    if text.endswith("마다"):
        body = text[:-2].strip()
        minutes = parse_duration(body)
        if minutes is None or minutes < _MIN_INTERVAL_MINUTES:
            return None
        return {"kind": "interval", "minutes": minutes,
                "display": f"{body}마다"}

    low = text.lower()
    if low.startswith("every "):
        minutes = parse_duration(low[6:])
        if minutes is None or minutes < _MIN_INTERVAL_MINUTES:
            return None
        return {"kind": "interval", "minutes": minutes,
                "display": f"every {low[6:].strip()}"}

    m = _CLOCK_RE.match(text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour > 23 or minute > 59:
            return None
        return {"kind": "daily", "hour": hour, "minute": minute,
                "display": f"{hour:02d}:{minute:02d} daily"}

    expr = cronexpr.normalize(text)
    if expr is not None:
        if _cron_next(expr, datetime.now()) is None:
            return None                       # unsatisfiable or malformed
        return {"kind": "cron", "expr": expr, "display": expr}

    minutes = parse_duration(text)
    if minutes is not None:
        run_at = datetime.now() + timedelta(minutes=minutes)
        return {"kind": "once", "run_at": run_at.isoformat(timespec="seconds"),
                "display": f"once at {run_at.strftime('%Y-%m-%d %H:%M')}"}

    try:                                       # ISO timestamp
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return {"kind": "once", "run_at": when.isoformat(timespec="seconds"),
            "display": f"once at {when.strftime('%Y-%m-%d %H:%M')}"}


def _cron_field_matches(field: str, value: int, lo: int, hi: int) -> bool:
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, _, raw_step = part.partition("/")
            if not raw_step.isdigit() or int(raw_step) == 0:
                return False
            step = int(raw_step)
        if part in ("*", ""):
            start, end = lo, hi
        elif "-" in part.lstrip("-"):
            a, _, b = part.partition("-")
            if not (a.isdigit() and b.isdigit()):
                return False
            start, end = int(a), int(b)
        elif part.isdigit():
            start = end = int(part)
            if step > 1:                      # "5/15" means 5,20,35... to hi
                end = hi
        else:
            return False
        if start <= value <= end and (value - start) % step == 0:
            return True
    return False


def _cron_next(expr: str, after: datetime) -> Optional[datetime]:
    """Next firing time strictly after ``after``, or None if never.

    ponytail: a minute-by-minute scan bounded to a year. It runs only when a
    job is created or claimed — never in a hot path — so a smarter search
    would be complexity with nothing to show for it. Swap in croniter if that
    ever stops being true.
    """
    parts = (cronexpr.normalize(expr) or expr).split()
    if len(parts) < 5:
        return None
    minute_f, hour_f, dom_f, month_f, dow_f = parts[:5]
    cur = (after.replace(second=0, microsecond=0) + timedelta(minutes=1))
    limit = cur + timedelta(days=_CRON_SEARCH_DAYS)
    while cur < limit:
        if not _cron_field_matches(month_f, cur.month, 1, 12):
            cur = (cur.replace(day=1, hour=0, minute=0)
                   + timedelta(days=32)).replace(day=1, hour=0, minute=0)
            continue
        # vixie semantics: when BOTH day-of-month and day-of-week are
        # restricted the job runs if EITHER matches; otherwise both must.
        dom_any, dow_any = dom_f.strip() == "*", dow_f.strip() == "*"
        dom_ok = _cron_field_matches(dom_f, cur.day, 1, 31)
        dow_ok = _cron_field_matches(dow_f, cur.isoweekday() % 7, 0, 6)
        day_ok = (dom_ok or dow_ok) if not dom_any and not dow_any \
            else (dom_ok and dow_ok)
        if not day_ok:
            cur = (cur + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if not _cron_field_matches(hour_f, cur.hour, 0, 23):
            cur = (cur + timedelta(hours=1)).replace(minute=0)
            continue
        if _cron_field_matches(minute_f, cur.minute, 0, 59):
            return cur
        cur += timedelta(minutes=1)
    return None


def compute_next_run(schedule: dict[str, Any],
                     last: datetime | None = None,
                     now: datetime | None = None) -> Optional[str]:
    """Next firing time as an ISO string, or None when the job is finished."""
    now = now or datetime.now()
    kind = schedule.get("kind")

    if kind == "once":
        run_at = schedule.get("run_at")
        return None if last else run_at       # a one-shot never re-arms

    if kind == "interval":
        base = last or now
        minutes = max(_MIN_INTERVAL_MINUTES, int(schedule.get("minutes", 60)))
        return (base + timedelta(minutes=minutes)).isoformat(timespec="seconds")

    if kind == "cron":
        nxt = _cron_next(str(schedule.get("expr", "")), last or now)
        return nxt.isoformat(timespec="seconds") if nxt else None

    # daily
    hour = int(schedule.get("hour", 9))
    minute = int(schedule.get("minute", 0))
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate.isoformat(timespec="seconds")


def schedule_display(job: dict[str, Any]) -> str:
    """Human-readable schedule for listings, legacy jobs included."""
    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        return str(schedule.get("display")
                   or schedule.get("expr") or schedule.get("kind", "?"))
    return f"{int(job.get('hour', 0)):02d}:{int(job.get('minute', 0)):02d}"


# -- storage ---------------------------------------------------------------

def load_jobs() -> list[dict[str, Any]]:
    return store._read_json(config.cron_path(), [])


def save_jobs(jobs: list[dict[str, Any]]) -> None:
    store._write_json(config.cron_path(), jobs)


def add_job(*, name: str, hour: int = 9, minute: int = 0,
            action_type: str = "prompt", value: str = "",
            enabled: bool = True, deliver_chat_id: str | None = None,
            schedule: str | dict[str, Any] | None = None) -> dict[str, Any]:
    """Register a job.

    ``schedule`` accepts an expression (``"every 30m"``, ``"0 9 * * 1"``, …) or
    an already-parsed dict. Callers that pass only ``hour``/``minute`` keep
    producing the original record shape.
    """
    parsed: Optional[dict[str, Any]] = None
    if isinstance(schedule, dict):
        parsed = schedule
    elif schedule:
        parsed = parse_schedule(schedule)
        if parsed is None:
            raise ValueError(f"unrecognized schedule: {schedule!r}")
    if parsed is not None and parsed.get("kind") == "daily":
        hour, minute = parsed["hour"], parsed["minute"]

    job = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "hour": int(hour),
        "minute": int(minute),
        "type": action_type,  # "prompt" | "shell"
        "value": value,
        "enabled": enabled,
        # Telegram chat to notify with the job's output (optional). The
        # scheduler honors the [SILENT] convention before sending.
        "deliver_chat_id": str(deliver_chat_id) if deliver_chat_id else None,
        "created": datetime.now().isoformat(timespec="seconds"),
        "last_run": None,
    }
    if parsed is not None:
        job["schedule"] = parsed
        job["next_run"] = compute_next_run(parsed)
        if job["next_run"] is None:
            raise ValueError(f"schedule never fires: {parsed.get('display')}")
    # cron.json is mutated by two processes (gateway /remind + scheduler
    # daemon mark_ran) — lock the whole read-modify-write so neither clobbers
    # the other's change (e.g. a mark_ran landing on a pre-delete snapshot).
    with store.file_lock(config.cron_path()):
        jobs = load_jobs()
        jobs.append(job)
        save_jobs(jobs)
    return job


def remove_job(job_id: str) -> bool:
    with store.file_lock(config.cron_path()):
        jobs = load_jobs()
        new = [j for j in jobs if j.get("id") != job_id]
        if len(new) == len(jobs):
            return False
        save_jobs(new)
    return True


def mark_ran(job_id: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with store.file_lock(config.cron_path()):
        jobs = [
            {**j, "last_run": now} if j.get("id") == job_id else j
            for j in load_jobs()
        ]
        save_jobs(jobs)


def claim_if_due(job_id: str, now: datetime | None = None) -> bool:
    """Atomically claim ``job_id`` for this caller, under the cron lock.

    Returns True only for the caller that won the claim — so two daemons
    reading the same due job can't both run it. The caller runs the job only
    when this returns True.

    Scheduled jobs advance ``next_run`` *before* the job executes and one-shots
    are deleted at claim time, which is what makes the claim at-most-once. A
    job lost to a crash between claim and execution is the accepted trade: for
    reminders, firing twice is worse than not firing.
    """
    now = now or datetime.now()
    stamp = now.isoformat(timespec="seconds")
    today = date.today().isoformat()
    try:
        with store.file_lock(config.cron_path()):
            jobs = load_jobs()
            job = next((j for j in jobs if j.get("id") == job_id), None)
            if job is None:
                return False
            schedule = job.get("schedule")

            if not isinstance(schedule, dict):      # legacy daily record
                if (job.get("last_run") or "")[:10] == today:
                    return False
                job["last_run"] = stamp
                save_jobs(jobs)
                return True

            if not _schedule_due(job, now):
                return False
            if schedule.get("kind") == "once":
                save_jobs([j for j in jobs if j.get("id") != job_id])
                return True
            job["last_run"] = stamp
            job["next_run"] = compute_next_run(schedule, last=now, now=now)
            save_jobs(jobs)
            return True
    except store.FileLockTimeout:
        return False


def _parse_dt(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _schedule_due(job: dict[str, Any], now: datetime) -> bool:
    schedule = job.get("schedule")
    if not isinstance(schedule, dict):
        return False
    next_run = job.get("next_run")
    if not next_run:      # hand-edited, or written by an older birkin
        # Recover from the job's own history, NOT from now: anchoring on now
        # would push the next run forward on every poll and the job would
        # never fire at all.
        anchor = _parse_dt(job.get("last_run")) or _parse_dt(job.get("created"))
        next_run = compute_next_run(schedule, last=anchor, now=now)
        if not next_run:
            return False
    try:
        return datetime.fromisoformat(next_run) <= now
    except (TypeError, ValueError):
        return False


def due_jobs(now: datetime | None = None) -> list[dict[str, Any]]:
    """Jobs that are enabled and whose schedule has come round."""
    now = now or datetime.now()
    # `date.today()` (local real today) intentionally matches mark_ran(), which
    # stamps last_run with datetime.now(); the scheduler always passes a local
    # `now`, so now.date() == today in production.
    today = date.today().isoformat()
    out = []
    for j in load_jobs():
        if not j.get("enabled", True):
            continue
        if isinstance(j.get("schedule"), dict):
            if _schedule_due(j, now):
                out.append(j)
            continue
        # Legacy daily record — original behavior, deliberately untouched.
        last = (j.get("last_run") or "")[:10]
        if last == today:
            continue
        if (now.hour, now.minute) >= (int(j.get("hour", 0)), int(j.get("minute", 0))):
            out.append(j)
    return out
