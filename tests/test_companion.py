"""Commitment / check-in domain: transitions, good silence, and dedupe.

Covers the plan's required-test list for milestones 1 and 3 — every branch that
decides whether Birkin contacts the user, plus the invariants that keep an LLM
from changing user state on its own.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from birkin import companion, config

KST = timezone(timedelta(hours=9))
CTX = "telegram:12345"
SOURCE = "telegram:12345:99"
BASE = datetime(2026, 8, 1, 9, 0, tzinfo=KST)

_TZDB = pytest.mark.skipif(not companion.tz_available(),
                           reason="no IANA tz database on this interpreter")


def _setup(**policy):
    """Bind the trusted chat and set a policy that isolates one rule per test.

    Caps/cooldown/expiry default to off here so a test that exercises quiet
    hours is not silently short-circuited by an unrelated limit.
    """
    companion.bind_context(CTX, owner_id="12345")
    settings = {"enabled": True, "timezone": "Asia/Seoul",
                "utc_offset_minutes": 540, "daily_cap": 0,
                "cooldown_minutes": 0, "expiry_minutes": 0,
                "quiet_hours": {"start": "22:00", "end": "08:00"}}
    settings.update(policy)
    companion.set_policy(**settings)
    return CTX


def _active(when=BASE, *, outcome="Send the proposal", source=SOURCE,
            next_action="", context_id=CTX):
    rec = companion.add_candidate(context_id=context_id, outcome=outcome,
                                  source_ref=source, next_action=next_action)
    return companion.activate(rec["id"], check_in_at=when.isoformat(),
                              tz_name="Asia/Seoul", utc_offset_minutes=540)


# -- trust invariants ------------------------------------------------------

def test_candidate_cannot_notify_before_confirmation():
    _setup()
    rec = companion.add_candidate(context_id=CTX, outcome="Send it",
                                  source_ref=SOURCE)
    assert rec["status"] == "candidate"
    ok, reason = companion.claim_checkin(rec["id"], now=BASE)
    assert not ok and reason == "commitment is candidate"


def test_commitment_requires_an_outcome_and_a_source_reference():
    _setup()
    with pytest.raises(companion.CompanionError):
        companion.add_candidate(context_id=CTX, outcome="  ", source_ref=SOURCE)
    with pytest.raises(companion.CompanionError):
        companion.add_candidate(context_id=CTX, outcome="Send it", source_ref="")


def test_group_chat_and_foreign_channel_are_denied_in_storage():
    with pytest.raises(companion.CompanionError):
        companion.bind_context("telegram:-1001234", owner_id="12345")
    with pytest.raises(companion.CompanionError):
        companion.bind_context("slack:C123", owner_id="12345")
    assert companion.is_private_chat("telegram:12345")
    assert not companion.is_private_chat("telegram:-1001234")
    assert not companion.is_private_chat("slack:C123")


def test_activation_requires_a_bound_active_context():
    companion.set_policy(enabled=True)
    rec = companion.add_candidate(context_id=CTX, outcome="Send it",
                                  source_ref=SOURCE)
    with pytest.raises(companion.CompanionError, match="context"):
        companion.activate(rec["id"], check_in_at=BASE.isoformat())


def test_one_active_commitment_per_context():
    _setup()
    _active()
    second = companion.add_candidate(context_id=CTX, outcome="Book the venue",
                                     source_ref="telegram:12345:100")
    with pytest.raises(companion.CompanionError, match="already has an active"):
        companion.activate(second["id"], check_in_at=BASE.isoformat())


def test_inferred_affect_never_enters_persistent_state():
    _setup()
    rec = _active()
    for key in ("emotion", "mood", "sentiment", "affect", "feeling"):
        with pytest.raises(companion.CompanionError, match="turn-local"):
            companion.append_event(kind="note", context_id=CTX,
                                   commitment_id=rec["id"], data={key: "sad"})


def test_proactive_contact_is_off_by_default():
    assert companion.default_policy()["enabled"] is False
    companion.bind_context(CTX, owner_id="12345")
    companion.set_policy(timezone="Asia/Seoul", utc_offset_minutes=540)
    rec = _active()
    ok, reason = companion.claim_checkin(rec["id"], now=BASE + timedelta(minutes=1))
    assert not ok and reason == "proactive contact is off"


def test_pause_all_takes_effect_before_the_next_send():
    _setup()
    rec = _active()
    companion.pause_all()
    ok, reason = companion.claim_checkin(rec["id"], now=BASE + timedelta(minutes=1))
    assert not ok and reason in ("proactive contact is off",
                                "policy changed after scheduling")
    # Re-stamped by the cancelled claim, so the next poll sees the real reason.
    ok, reason = companion.claim_checkin(rec["id"], now=BASE + timedelta(minutes=2))
    assert not ok and reason == "proactive contact is off"


# -- state transitions ----------------------------------------------------

def test_invalid_transition_is_rejected():
    _setup()
    rec = companion.add_candidate(context_id=CTX, outcome="Send it",
                                  source_ref=SOURCE)
    with pytest.raises(companion.CompanionError, match="invalid transition"):
        companion.answer(rec["id"], "done")


def test_unknown_action_is_rejected():
    _setup()
    rec = _active()
    with pytest.raises(companion.CompanionError, match="unknown action"):
        companion.answer(rec["id"], "maybe")


def test_terminal_state_rejects_a_reschedule():
    _setup()
    rec = _active()
    companion.answer(rec["id"], "done")
    with pytest.raises(companion.CompanionError, match="invalid transition"):
        companion.reschedule(rec["id"], check_in_at=(BASE + timedelta(days=1)).isoformat())


def test_blocked_captures_the_next_action():
    _setup()
    rec = _active()
    res = companion.answer(rec["id"], "blocked", next_action="Ask Jin for the data")
    assert res["status"] == "blocked"
    assert res["commitment"]["next_action"] == "Ask Jin for the data"
    assert "Ask Jin for the data" in res["message"]


def test_snooze_moves_the_check_in_time():
    _setup()
    rec = _active()
    res = companion.answer(rec["id"], "snooze", snooze_minutes=30,
                           now=BASE + timedelta(minutes=1))
    assert res["status"] == "snoozed"
    assert companion.parse_iso(res["commitment"]["check_in_at"]) == \
        BASE + timedelta(minutes=31)


def test_wrong_stops_the_asking_and_keeps_the_correction_separate():
    _setup()
    rec = _active()
    res = companion.answer(rec["id"], "wrong")
    assert res["status"] == "stopped"
    assert res["commitment"]["wrong"] is True
    corrected = companion.correct(rec["id"], outcome="Send the invoice")
    assert corrected["revision"] == 2
    events = companion.read_events(commitment_id=rec["id"])
    correction = [e for e in events if e["type"] == "commitment_corrected"][-1]
    assert correction["data"]["previous"]["outcome"] == "Send the proposal"


def test_correction_supersedes_the_previous_revision_without_losing_provenance():
    _setup()
    rec = _active()
    companion.correct(rec["id"], outcome="Send the revised proposal",
                      next_action="Rewrite section 2")
    after = companion.get_commitment(rec["id"])
    assert after["outcome"] == "Send the revised proposal"
    assert after["revision"] == 2
    assert after["source_ref"] == SOURCE


def test_reschedule_moves_an_open_commitment_only():
    _setup()
    rec = _active()
    moved = companion.reschedule(rec["id"],
                                 check_in_at=(BASE + timedelta(days=1)).isoformat())
    assert moved["status"] == "active"
    assert companion.parse_iso(moved["check_in_at"]) == BASE + timedelta(days=1)
    assert moved["checkin"] is None


# -- idempotency and at-most-once delivery --------------------------------

def test_repeated_callback_is_idempotent():
    _setup()
    rec = _active()
    first = companion.answer(rec["id"], "done")
    second = companion.answer(rec["id"], "done")
    assert first["repeat"] is False and second["repeat"] is True
    assert second["status"] == "done"
    answered = [e for e in companion.read_events(commitment_id=rec["id"])
                if e["type"] == "checkin_answered"]
    assert len(answered) == 1


def test_a_different_answer_after_an_answer_is_refused():
    _setup()
    rec = _active()
    companion.answer(rec["id"], "done")
    with pytest.raises(companion.CompanionError, match="already answered"):
        companion.answer(rec["id"], "blocked")


def test_two_daemons_cannot_send_the_same_check_in():
    _setup()
    rec = _active()
    now = BASE + timedelta(minutes=1)
    results: list[tuple[bool, str]] = []
    lock = threading.Lock()

    def claim():
        outcome = companion.claim_checkin(rec["id"], now=now)
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=claim) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert sum(1 for ok, _ in results if ok) == 1


def test_restart_after_scheduling_does_not_duplicate_delivery():
    _setup()
    rec = _active()
    now = BASE + timedelta(minutes=1)
    ok, key = companion.claim_checkin(rec["id"], now=now)
    assert ok
    # A restarted daemon re-reads state.json and finds the same due commitment.
    again_ok, reason = companion.claim_checkin(rec["id"], now=now + timedelta(minutes=1))
    assert not again_ok and reason == "previous check-in is still open"
    sends = companion.load_state()["sends"]
    assert [s["key"] for s in sends] == [key]


def test_dedupe_key_is_per_check_in_time():
    _setup()
    rec = _active()
    ok, first_key = companion.claim_checkin(rec["id"], now=BASE + timedelta(minutes=1))
    assert ok
    later = BASE + timedelta(hours=2)
    companion.reschedule(rec["id"], check_in_at=later.isoformat())
    ok, second_key = companion.claim_checkin(rec["id"], now=later + timedelta(minutes=1))
    assert ok and second_key != first_key


def test_record_delivery_retains_the_telegram_message_id():
    _setup()
    rec = _active()
    companion.claim_checkin(rec["id"], now=BASE + timedelta(minutes=1))
    companion.record_delivery(rec["id"], "4242")
    assert companion.get_commitment(rec["id"])["checkin"]["message_id"] == "4242"


# -- good silence ---------------------------------------------------------

def test_quiet_hours_crossing_midnight_suppresses_the_send():
    _setup(quiet_hours={"start": "22:00", "end": "08:00"})
    night = datetime(2026, 8, 1, 23, 30, tzinfo=KST)
    rec = _active(night)
    ok, reason = companion.claim_checkin(rec["id"], now=night + timedelta(minutes=1))
    assert not ok and reason == "inside quiet hours"
    morning = datetime(2026, 8, 2, 9, 0, tzinfo=KST)
    ok, _ = companion.claim_checkin(rec["id"], now=morning)
    assert ok


def test_quiet_hours_window_that_does_not_wrap():
    _setup(quiet_hours={"start": "09:00", "end": "17:00"})
    rec = _active(datetime(2026, 8, 1, 10, 0, tzinfo=KST))
    ok, reason = companion.claim_checkin(
        rec["id"], now=datetime(2026, 8, 1, 10, 1, tzinfo=KST))
    assert not ok and reason == "inside quiet hours"
    ok, _ = companion.claim_checkin(
        rec["id"], now=datetime(2026, 8, 1, 17, 30, tzinfo=KST))
    assert ok


def test_daily_cap_blocks_a_second_send():
    _setup(daily_cap=1)
    rec = _active()
    ok, _ = companion.claim_checkin(rec["id"], now=BASE + timedelta(minutes=1))
    assert ok
    companion.answer(rec["id"], "done", now=BASE + timedelta(minutes=2))
    second = _active(BASE + timedelta(minutes=30), outcome="Book the venue",
                     source="telegram:12345:100")
    ok, reason = companion.claim_checkin(second["id"],
                                         now=BASE + timedelta(minutes=31))
    assert not ok and reason == "daily cap reached"
    # The cap is per policy-local day, so tomorrow is allowed again.
    tomorrow = BASE + timedelta(days=1)
    companion.reschedule(second["id"], check_in_at=tomorrow.isoformat())
    ok, _ = companion.claim_checkin(second["id"], now=tomorrow + timedelta(minutes=1))
    assert ok


def test_cooldown_blocks_a_second_send():
    _setup(cooldown_minutes=720)
    rec = _active()
    ok, _ = companion.claim_checkin(rec["id"], now=BASE + timedelta(minutes=1))
    assert ok
    companion.answer(rec["id"], "done", now=BASE + timedelta(minutes=2))
    second = _active(BASE + timedelta(hours=1), outcome="Book the venue",
                     source="telegram:12345:100")
    ok, reason = companion.claim_checkin(second["id"],
                                        now=BASE + timedelta(hours=1, minutes=1))
    assert not ok and reason == "inside cooldown"
    # 21:02 KST — past the 720-minute cooldown and still outside quiet hours
    # (BASE + 13h is 22:00, inside the window this test configures).
    ok, _ = companion.claim_checkin(second["id"],
                                    now=BASE + timedelta(hours=12, minutes=2))
    assert ok


def test_policy_change_after_scheduling_cancels_the_pending_send():
    _setup()
    rec = _active()
    companion.set_policy(daily_cap=5)
    now = BASE + timedelta(minutes=1)
    ok, reason = companion.claim_checkin(rec["id"], now=now)
    assert not ok and reason == "policy changed after scheduling"
    # Re-stamped to the policy the user actually has now, then allowed.
    ok, _ = companion.claim_checkin(rec["id"], now=now + timedelta(minutes=1))
    assert ok


def test_expired_check_in_is_not_delivered_as_a_backlog():
    _setup(expiry_minutes=60)
    rec = _active()
    ok, reason = companion.claim_checkin(rec["id"], now=BASE + timedelta(hours=3))
    assert not ok and reason == "check-in expired"


def test_catch_up_opts_in_to_a_late_delivery():
    _setup(expiry_minutes=60, catch_up=True)
    rec = _active()
    ok, _ = companion.claim_checkin(rec["id"], now=BASE + timedelta(hours=3))
    assert ok


def test_repeatedly_ignored_check_ins_stop_the_asking():
    _setup(expiry_minutes=60, catch_up=True)
    rec = _active()
    for hour in range(3):
        slot = BASE + timedelta(hours=hour)
        companion.reschedule(rec["id"], check_in_at=slot.isoformat())
        ok, _ = companion.claim_checkin(rec["id"], now=slot + timedelta(minutes=1))
        assert ok
        # Aged out unanswered — counts against the ignored streak.
        companion.claim_checkin(rec["id"], now=slot + timedelta(minutes=62))
    assert companion.get_commitment(rec["id"])["ignored_streak"] == 3
    slot = BASE + timedelta(hours=4)
    companion.reschedule(rec["id"], check_in_at=slot.isoformat())
    ok, reason = companion.claim_checkin(rec["id"], now=slot + timedelta(minutes=1))
    assert not ok and reason == "recent check-ins were ignored"


def test_answering_clears_the_ignored_streak():
    _setup(expiry_minutes=60, catch_up=True)
    rec = _active()
    companion.claim_checkin(rec["id"], now=BASE + timedelta(minutes=1))
    companion.claim_checkin(rec["id"], now=BASE + timedelta(minutes=62))
    assert companion.get_commitment(rec["id"])["ignored_streak"] == 1
    companion.reschedule(rec["id"], check_in_at=(BASE + timedelta(hours=2)).isoformat())
    companion.claim_checkin(rec["id"], now=BASE + timedelta(hours=2, minutes=1))
    companion.answer(rec["id"], "done", now=BASE + timedelta(hours=2, minutes=5))
    assert companion.get_commitment(rec["id"])["ignored_streak"] == 0


def test_deleted_commitment_prevents_a_later_check_in():
    _setup()
    rec = _active()
    assert companion.delete_commitment(rec["id"]) is True
    ok, reason = companion.claim_checkin(rec["id"], now=BASE + timedelta(minutes=1))
    assert not ok and reason == "no such commitment"
    assert companion.get_commitment(rec["id"]) is None
    assert companion.load_state()["sends"] == []
    assert companion.delete_commitment(rec["id"]) is False


def test_a_commitment_without_a_source_reference_cannot_notify():
    _setup()
    rec = _active()
    state = companion.load_state()
    state["commitments"][rec["id"]]["source_ref"] = ""
    companion._save_state(state)
    ok, reason = companion.claim_checkin(rec["id"], now=BASE + timedelta(minutes=1))
    assert not ok and reason == "commitment has no source reference"


def test_context_turned_off_stops_proactive_contact():
    _setup()
    rec = _active()
    state = companion.load_state()
    state["contexts"][CTX]["proactive_mode"] = "off"
    companion._save_state(state)
    ok, reason = companion.claim_checkin(rec["id"], now=BASE + timedelta(minutes=1))
    assert not ok and reason == "context has proactive mode off"


def test_due_checkins_only_returns_due_active_commitments():
    _setup()
    rec = _active()
    assert companion.due_checkins(now=BASE - timedelta(minutes=1)) == []
    assert [r["id"] for r in companion.due_checkins(now=BASE)] == [rec["id"]]
    companion.answer(rec["id"], "done")
    assert companion.due_checkins(now=BASE + timedelta(hours=1)) == []


# -- timezone handling ----------------------------------------------------

@_TZDB
def test_dst_boundary_changes_the_offset():
    winter = datetime(2026, 1, 15, 12, tzinfo=companion.resolve_tz("America/New_York"))
    summer = datetime(2026, 7, 15, 12, tzinfo=companion.resolve_tz("America/New_York"))
    assert winter.utcoffset() == timedelta(hours=-5)
    assert summer.utcoffset() == timedelta(hours=-4)


@_TZDB
def test_quiet_hours_follow_dst_in_the_policy_zone():
    companion.bind_context(CTX, owner_id="12345")
    companion.set_policy(enabled=True, timezone="America/New_York",
                         daily_cap=0, cooldown_minutes=0, expiry_minutes=0,
                         quiet_hours={"start": "22:00", "end": "08:00"})
    ny = companion.resolve_tz("America/New_York")
    summer_evening = datetime(2026, 7, 15, 23, 0, tzinfo=ny)
    rec = _active(summer_evening)
    ok, reason = companion.claim_checkin(rec["id"],
                                        now=summer_evening + timedelta(minutes=1))
    assert not ok and reason == "inside quiet hours"


def test_fixed_offset_is_the_documented_fallback_without_a_tz_database():
    resolved = companion.resolve_tz("Not/AZone", 540)
    assert datetime(2026, 8, 1, tzinfo=resolved).utcoffset() == timedelta(hours=9)


@pytest.mark.parametrize("offset_minutes", [-1440, 1440])
def test_invalid_fixed_offset_is_rejected_without_mutating_policy(
        offset_minutes):
    before = companion.get_policy()

    with pytest.raises(
        companion.CompanionError,
        match="utc_offset_minutes",
    ):
        companion.set_policy(utc_offset_minutes=offset_minutes)

    assert companion.get_policy() == before


def test_invalid_persisted_fixed_offset_recovers_to_utc():
    state = companion._blank_state()
    state["policy"]["timezone"] = "Missing/Zone"
    state["policy"]["utc_offset_minutes"] = 1440
    companion._save_state(state)

    policy = companion.get_policy()
    assert policy["utc_offset_minutes"] == 0
    resolved = companion.resolve_tz(
        policy["timezone"],
        policy["utc_offset_minutes"],
    )
    assert datetime(2026, 8, 1, tzinfo=resolved).utcoffset() == timedelta(0)


# -- storage and events ---------------------------------------------------

def test_events_are_append_only_and_source_linked():
    _setup()
    rec = _active()
    companion.claim_checkin(rec["id"], now=BASE + timedelta(minutes=1))
    companion.answer(rec["id"], "done", now=BASE + timedelta(minutes=5))
    kinds = [e["type"] for e in companion.read_events(commitment_id=rec["id"])]
    assert kinds == ["commitment_proposed", "commitment_activated",
                     "checkin_sent", "checkin_answered"]
    assert all(e["source_ref"] == SOURCE
               for e in companion.read_events(commitment_id=rec["id"]))


def test_events_never_store_a_conversation_body():
    _setup()
    rec = _active()
    raw = config.companion_events_path().read_text(encoding="utf-8")
    assert SOURCE in raw          # the reference is kept
    assert rec["outcome"] in raw  # the confirmed outcome is kept
    for event in companion.read_events(commitment_id=rec["id"]):
        assert len(event["summary"]) <= 200


def test_corrupt_state_file_falls_back_to_a_blank_state():
    config.companion_state_path().write_text("not json", encoding="utf-8")
    state = companion.load_state()
    assert state["commitments"] == {} and state["contexts"] == {}
    assert state["policy"]["enabled"] is False


def test_unknown_policy_key_is_rejected():
    with pytest.raises(companion.CompanionError, match="unknown policy keys"):
        companion.set_policy(nagging=True)


def test_quiet_hours_must_be_valid_clock_times():
    for window in ({"start": "9", "end": "17:00"},
                   {"start": "25:00", "end": "08:00"},
                   {"start": "22:00", "end": "08:99"}):
        with pytest.raises(companion.CompanionError, match="HH:MM"):
            companion.set_policy(quiet_hours=window)


def test_policy_version_increments_on_every_change():
    first = companion.set_policy(enabled=True)["version"]
    second = companion.set_policy(daily_cap=2)["version"]
    assert second == first + 1


def test_why_message_names_the_commitment_and_its_source():
    _setup()
    rec = _active()
    why = companion.why_message(rec)
    assert rec["outcome"] in why and SOURCE in why
    assert rec["check_in_at"] in why
