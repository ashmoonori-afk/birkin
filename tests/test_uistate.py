"""UI state contract: single Python-owned source of truth for every surface.

Spec (docs/ui/DESIGN.md): nine states, attention-first ordering, quad-redundant
encoding (glyph + ascii + label + color role), pure mapping from the raw status
strings that actually exist in the runtime today, and a JSON-Schema export so
non-Python surfaces generate types instead of hand-copying them.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from birkin import uistate


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# -- state set --------------------------------------------------------------

def test_state_set_is_the_contract():
    assert uistate.UI_STATES == (
        "running", "waiting_human", "waiting_dependency", "idle", "paused",
        "completed", "failed", "expired", "unknown")


def test_attention_order_puts_human_blockers_first():
    ranked = sorted(uistate.UI_STATES, key=uistate.attention_rank)
    assert ranked[0] == "waiting_human"
    assert ranked[1] == "failed"
    assert ranked[2] == "expired"
    # completed work never outranks live or blocked work
    assert ranked.index("completed") > ranked.index("running")
    assert ranked.index("completed") > ranked.index("waiting_dependency")


# -- quad-redundant encoding (never color alone) ----------------------------

def test_every_state_has_distinct_glyph_label_and_ascii():
    glyphs = [uistate.glyph(s) for s in uistate.UI_STATES]
    asciis = [uistate.glyph(s, ascii_only=True) for s in uistate.UI_STATES]
    labels = [uistate.label(s) for s in uistate.UI_STATES]
    assert len(set(glyphs)) == len(glyphs)
    assert len(set(asciis)) == len(asciis)
    assert len(set(labels)) == len(labels)
    for a in asciis:
        assert a.isascii() and 1 <= len(a) <= 2


def test_states_that_must_never_share_a_symbol():
    # waiting-for-human vs waiting-for-dependency vs idle vs completed vs failed
    critical = ["waiting_human", "waiting_dependency", "idle", "completed",
                "failed"]
    for view in (dict(ascii_only=True), dict(ascii_only=False)):
        marks = {s: uistate.glyph(s, **view) for s in critical}
        assert len(set(marks.values())) == len(critical), marks


def test_every_state_has_a_color_role():
    for s in uistate.UI_STATES:
        role = uistate.color_role(s)
        assert isinstance(role, str) and role


# -- mapping: approvals (store.py pending records) --------------------------

def test_pending_approval_waits_for_human():
    rec = {"status": "pending"}
    assert uistate.from_approval(rec).state == "waiting_human"


def test_pending_approval_past_expiry_is_expired():
    past = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
    rec = {"status": "pending", "expires_at": past}
    assert uistate.from_approval(rec).state == "expired"


def test_pending_approval_with_future_expiry_still_waits():
    future = _iso(datetime.now(timezone.utc) + timedelta(minutes=5))
    rec = {"status": "pending", "expires_at": future}
    assert uistate.from_approval(rec).state == "waiting_human"


def test_in_flight_approval_states_map_to_running():
    for raw in ("claimed", "approving", "executing", "resuming"):
        view = uistate.from_approval({"status": raw})
        assert view.state == "running", raw
        assert view.raw == raw


def test_resume_pending_waits_on_dependency_not_human():
    view = uistate.from_approval({"status": "resume_pending"})
    assert view.state == "waiting_dependency"


def test_terminal_approval_states():
    assert uistate.from_approval({"status": "approved"}).state == "completed"
    assert uistate.from_approval({"status": "completed"}).state == "completed"
    assert uistate.from_approval({"status": "rejected"}).state == "completed"
    assert uistate.from_approval({"status": "error"}).state == "failed"
    assert uistate.from_approval({"status": "expired"}).state == "expired"
    # interrupted work is resumable, not dead
    assert uistate.from_approval({"status": "interrupted"}).state == "paused"


def test_unmapped_approval_status_is_unknown_never_invented():
    view = uistate.from_approval({"status": "some_future_status"})
    assert view.state == "unknown"
    assert view.raw == "some_future_status"


# -- mapping: background jobs (background_receipts.JobStatus) ---------------

def test_job_states():
    assert uistate.from_job("queued").state == "waiting_dependency"
    assert uistate.from_job("running").state == "running"
    assert uistate.from_job("succeeded").state == "completed"
    assert uistate.from_job("failed").state == "failed"
    # cancelled is a deliberate, non-resumable stop: resolved, not an error
    assert uistate.from_job("cancelled").state == "completed"
    assert uistate.from_job("cancelled").raw == "cancelled"


def test_scheduled_cron_state_uses_python_contract():
    assert uistate.from_cron(enabled=True).state == "idle"
    assert uistate.from_cron(enabled=False).state == "paused"


def test_recent_run_state_surfaces_recorded_errors():
    assert uistate.from_recent_run({"details": {}}).state == "completed"
    assert uistate.from_recent_run(
        {"details": {"error": "provider failed"}},
    ).state == "failed"
    assert uistate.from_recent_run(
        {"summary": "[nightly] error: provider failed", "details": {}},
    ).state == "failed"
    assert uistate.from_recent_run(
        {"summary": "daemon morpheus error: provider failed", "details": {}},
    ).state == "failed"
    assert uistate.from_recent_run(
        {"summary": "morpheus failed: provider failed", "details": {}},
    ).state == "failed"
    assert uistate.from_recent_run(
        {"summary": "[build] exit 1", "details": {}},
    ).state == "failed"
    assert uistate.from_recent_run(
        {"summary": "[build] exit 0", "details": {}},
    ).state == "completed"
    assert uistate.from_recent_run(
        {"summary": "error: provider failed", "details": {}},
    ).state == "failed"
    assert uistate.from_recent_run(
        {"summary": "failed: provider failed", "details": {}},
    ).state == "failed"
    assert uistate.from_recent_run(
        {"summary": "[build] exit 0 after retry", "details": {}},
    ).state == "completed"
    assert uistate.from_recent_run(
        {"summary": "[build] exit 0.", "details": {}},
    ).state == "completed"
    assert uistate.from_recent_run(
        {"summary": "[build] exit 12abc", "details": {}},
    ).state == "completed"
    assert uistate.from_recent_run(
        {"summary": "[build] exit 1.5", "details": {}},
    ).state == "completed"


# -- mapping: agent runs (agentruns._STATUSES) ------------------------------

def test_agent_run_states():
    assert uistate.from_agent_run("running").state == "running"
    assert uistate.from_agent_run("done").state == "completed"
    assert uistate.from_agent_run("error").state == "failed"
    # stale = heartbeat lost: we genuinely do not know; never guess
    assert uistate.from_agent_run("stale").state == "unknown"


# -- mapping: goals ---------------------------------------------------------

def test_goal_states():
    assert uistate.from_goal("active").state == "running"
    assert uistate.from_goal("paused").state == "paused"
    assert uistate.from_goal("done").state == "completed"


# -- mapping: moirai journal calls ------------------------------------------

def test_moirai_states():
    assert uistate.from_moirai("running").state == "running"
    assert uistate.from_moirai("completed").state == "completed"
    assert uistate.from_moirai("error").state == "failed"
    assert uistate.from_moirai("aborted").state == "failed"


# -- attention sorting over mixed records -----------------------------------

def test_attention_sort_orders_mixed_work():
    items = [
        uistate.from_job("succeeded"),
        uistate.from_approval({"status": "pending"}),
        uistate.from_agent_run("running"),
        uistate.from_job("failed"),
        uistate.from_job("queued"),
    ]
    ordered = sorted(items, key=lambda v: uistate.attention_rank(v.state))
    assert [v.state for v in ordered] == [
        "waiting_human", "failed", "running", "waiting_dependency",
        "completed"]


# -- schema export: single source for non-Python surfaces -------------------

def test_schema_exports_states_and_encoding():
    schema = uistate.schema()
    assert schema["$schema"].startswith("https://json-schema.org/")
    enum = schema["properties"]["state"]["enum"]
    assert tuple(enum) == uistate.UI_STATES
    enc = schema["x-birkin-encoding"]
    for s in uistate.UI_STATES:
        assert enc[s]["glyph"] == uistate.glyph(s)
        assert enc[s]["ascii"] == uistate.glyph(s, ascii_only=True)
        assert enc[s]["label"] == uistate.label(s)
        assert enc[s]["color_role"] == uistate.color_role(s)
        assert enc[s]["attention"] == uistate.attention_rank(s)


def test_schema_is_json_serializable_and_stable():
    import json
    a = json.dumps(uistate.schema(), sort_keys=True, ensure_ascii=False)
    b = json.dumps(uistate.schema(), sort_keys=True, ensure_ascii=False)
    assert a == b


# -- mapping: runtime events ------------------------------------------------

def test_from_runtime_tool_end_error_is_failed() -> None:
    view = uistate.from_runtime("tool_end", is_error=True)

    assert view.state == "failed"
    assert view.raw == "tool_end"
    assert view.domain == "runtime"


@pytest.mark.parametrize(
    ("event", "is_error"),
    [
        (event, is_error)
        for event in (
            "tool_start",
            "tool_end",
            "subagent.start",
            "subagent.done",
            "compact",
            "steer",
            "no_such_event",
        )
        for is_error in (False, True)
    ],
)
def test_from_runtime_totality(event: str, is_error: bool) -> None:
    view = uistate.from_runtime(event, is_error=is_error)

    assert view.state in uistate.UI_STATES
    if event == "no_such_event" and not is_error:
        assert view.state == "unknown"
    if is_error:
        assert view.state == "failed"
