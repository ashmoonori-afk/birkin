"""Rich cron schedules: intervals, one-shots, cron expressions, back-compat."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from birkin import cron


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    yield tmp_path


# -- grammar ---------------------------------------------------------------

@pytest.mark.parametrize("text,minutes", [
    ("30m", 30), ("2h", 120), ("1d", 1440), ("45 min", 45),
    ("3 hours", 180), ("2 days", 2880),
])
def test_parse_duration(text, minutes):
    assert cron.parse_duration(text) == minutes


@pytest.mark.parametrize("text", ["", "soon", "30", "m", "-5m", "1w"])
def test_parse_duration_rejects_junk(text):
    assert cron.parse_duration(text) is None


def test_parse_schedule_shapes():
    assert cron.parse_schedule("every 30m") == {
        "kind": "interval", "minutes": 30, "display": "every 30m"}
    daily = cron.parse_schedule("09:05")
    assert (daily["kind"], daily["hour"], daily["minute"]) == ("daily", 9, 5)
    assert cron.parse_schedule("0 9 * * 1")["kind"] == "cron"
    assert cron.parse_schedule("2h")["kind"] == "once"
    assert cron.parse_schedule("2026-07-24T09:00")["kind"] == "once"


@pytest.mark.parametrize("text", [
    "", "tomorrow", "25:00", "09:70", "every", "every banana", "every 0m",
])
def test_parse_schedule_rejects_junk(text):
    assert cron.parse_schedule(text) is None


def test_one_shot_run_at_is_in_the_future():
    spec = cron.parse_schedule("90m")
    delta = datetime.fromisoformat(spec["run_at"]) - datetime.now()
    assert timedelta(minutes=89) < delta <= timedelta(minutes=90)


# -- cron expression matcher ----------------------------------------------

def _next(expr, after="2026-07-23T10:30:00"):
    return cron._cron_next(expr, datetime.fromisoformat(after))


def test_cron_every_minute_and_hour():
    assert _next("* * * * *") == datetime(2026, 7, 23, 10, 31)
    assert _next("0 * * * *") == datetime(2026, 7, 23, 11, 0)


def test_cron_daily_and_step():
    assert _next("0 9 * * *") == datetime(2026, 7, 24, 9, 0)
    assert _next("*/15 * * * *") == datetime(2026, 7, 23, 10, 45)


def test_cron_ranges_and_lists():
    assert _next("0 9-17 * * *") == datetime(2026, 7, 23, 11, 0)
    assert _next("0 0,12 * * *") == datetime(2026, 7, 23, 12, 0)


def test_cron_day_of_week():
    # 2026-07-23 is a Thursday; the next Monday 09:00 is 2026-07-27.
    assert _next("0 9 * * 1") == datetime(2026, 7, 27, 9, 0)


def test_cron_dom_and_dow_use_vixie_or_semantics():
    # Either the 1st of the month OR a Monday — whichever comes first.
    assert _next("0 9 1 * 1") == datetime(2026, 7, 27, 9, 0)
    # With only day-of-month restricted, it must be the 1st.
    assert _next("0 9 1 * *") == datetime(2026, 8, 1, 9, 0)


def test_cron_month_field():
    assert _next("0 9 1 1 *") == datetime(2027, 1, 1, 9, 0)


def test_unsatisfiable_cron_terminates_and_is_rejected():
    assert _next("0 9 30 2 *") is None            # February 30th
    assert cron.parse_schedule("0 9 30 2 *") is None


def test_malformed_cron_fields_are_rejected():
    assert cron.parse_schedule("0 9 * * abc") is None
    assert _next("bad 9 * * *") is None


# -- next-run math ---------------------------------------------------------

def test_compute_next_run_interval_counts_from_last_run():
    last = datetime(2026, 7, 23, 10, 0)
    nxt = cron.compute_next_run({"kind": "interval", "minutes": 30}, last=last)
    assert datetime.fromisoformat(nxt) == datetime(2026, 7, 23, 10, 30)


def test_compute_next_run_one_shot_never_rearms():
    spec = {"kind": "once", "run_at": "2026-07-23T10:00:00"}
    assert cron.compute_next_run(spec) == "2026-07-23T10:00:00"
    assert cron.compute_next_run(spec, last=datetime.now()) is None


def test_compute_next_run_daily_rolls_to_tomorrow():
    now = datetime(2026, 7, 23, 10, 0)
    nxt = cron.compute_next_run({"kind": "daily", "hour": 9, "minute": 0},
                                now=now)
    assert datetime.fromisoformat(nxt) == datetime(2026, 7, 24, 9, 0)


# -- job lifecycle ---------------------------------------------------------

def test_interval_job_advances_next_run_on_claim():
    job = cron.add_job(name="poll", action_type="prompt", value="check mail",
                       schedule="every 30m")
    assert job["schedule"]["kind"] == "interval"

    later = datetime.fromisoformat(job["next_run"]) + timedelta(seconds=1)
    assert [j["id"] for j in cron.due_jobs(later)] == [job["id"]]
    assert cron.claim_if_due(job["id"], later) is not None

    stored = cron.load_jobs()[0]
    assert datetime.fromisoformat(stored["next_run"]) > later
    assert cron.due_jobs(later) == []          # not due again immediately


def test_claim_is_at_most_once_for_intervals():
    job = cron.add_job(name="poll", action_type="prompt", value="x",
                       schedule="every 30m")
    later = datetime.fromisoformat(job["next_run"]) + timedelta(seconds=1)
    assert cron.claim_if_due(job["id"], later) is not None
    assert cron.claim_if_due(job["id"], later) is None   # the loser


def test_one_shot_fires_once_then_disappears():
    job = cron.add_job(name="ping", action_type="prompt", value="stretch",
                       schedule="1m")
    later = datetime.fromisoformat(job["next_run"]) + timedelta(seconds=1)
    assert [j["id"] for j in cron.due_jobs(later)] == [job["id"]]
    assert cron.claim_if_due(job["id"], later) is not None
    assert cron.load_jobs() == []
    assert cron.claim_if_due(job["id"], later) is None


def test_not_due_before_its_time():
    job = cron.add_job(name="poll", action_type="prompt", value="x",
                       schedule="every 30m")
    early = datetime.fromisoformat(job["next_run"]) - timedelta(minutes=1)
    assert cron.due_jobs(early) == []
    assert cron.claim_if_due(job["id"], early) is None


def test_cron_job_roundtrip():
    job = cron.add_job(name="weekly", action_type="prompt", value="review",
                       schedule="0 9 * * 1")
    assert job["schedule"]["expr"] == "0 9 * * 1"
    assert datetime.fromisoformat(job["next_run"]).isoweekday() == 1


def test_add_job_rejects_an_unparseable_schedule():
    with pytest.raises(ValueError):
        cron.add_job(name="x", action_type="prompt", value="v",
                     schedule="whenever i feel like it")


def test_daily_schedule_expression_also_fills_hour_minute():
    job = cron.add_job(name="d", action_type="prompt", value="v",
                       schedule="07:30")
    assert (job["hour"], job["minute"]) == (7, 30)


# -- back-compat with pre-grammar records ---------------------------------

def test_legacy_daily_record_still_fires_exactly_once_a_day():
    job = cron.add_job(name="old", hour=9, minute=0, action_type="prompt",
                       value="legacy")
    assert job["schema_version"] == 1
    assert job["schedule"]["kind"] == "daily"

    # Anchor on the job's own armed time: a daily job is due from its next
    # occurrence onward, whatever the wall clock says when the test runs.
    now = datetime.fromisoformat(job["next_run"]) + timedelta(hours=1)
    assert [j["id"] for j in cron.due_jobs(now)] == [job["id"]]
    assert cron.claim_if_due(job["id"], now) is not None
    assert cron.claim_if_due(job["id"], now) is None       # already ran today
    assert cron.due_jobs(now) == []


def test_legacy_and_scheduled_jobs_coexist():
    legacy = cron.add_job(name="old", hour=0, minute=0, action_type="prompt",
                          value="legacy")
    modern = cron.add_job(name="new", action_type="prompt", value="new",
                          schedule="every 15m")
    later = max(datetime.fromisoformat(legacy["next_run"]),
                datetime.fromisoformat(modern["next_run"])) + timedelta(seconds=1)
    due = {j["id"] for j in cron.due_jobs(later)}
    assert due == {legacy["id"], modern["id"]}


def test_schedule_display_covers_both_shapes():
    legacy = cron.add_job(name="old", hour=9, minute=5, action_type="prompt",
                          value="v")
    assert cron.schedule_display(legacy) == "09:05"
    modern = cron.add_job(name="new", action_type="prompt", value="v",
                          schedule="every 2h")
    assert cron.schedule_display(modern) == "every 2h"


def test_a_job_without_next_run_recovers_from_its_own_history():
    job = cron.add_job(name="x", action_type="prompt", value="v",
                       schedule="every 30m")
    jobs = cron.load_jobs()
    jobs[0].pop("next_run")
    jobs[0]["created"] = (datetime.now() - timedelta(hours=2)).isoformat()
    cron.save_jobs(jobs)

    # Anchored on `created`, the interval already elapsed — so it fires.
    # (Anchoring on `now` instead would postpone it on every poll, forever.)
    assert [j["id"] for j in cron.due_jobs(datetime.now())] == [job["id"]]
    assert cron.claim_if_due(job["id"], datetime.now()) is not None
    assert cron.load_jobs()[0]["next_run"]      # re-armed properly


def test_a_fresh_job_without_next_run_waits_for_its_interval():
    cron.add_job(name="x", action_type="prompt", value="v",
                 schedule="every 30m")
    jobs = cron.load_jobs()
    jobs[0].pop("next_run")
    cron.save_jobs(jobs)
    assert cron.due_jobs(datetime.now()) == []


def test_disabled_jobs_never_fire():
    job = cron.add_job(name="x", action_type="prompt", value="v",
                       schedule="every 1m", enabled=False)
    later = datetime.fromisoformat(job["next_run"]) + timedelta(minutes=5)
    assert cron.due_jobs(later) == []


# -- Korean grammar (the project's primary language) ------------------------

@pytest.mark.parametrize("text,minutes", [
    ("30분", 30), ("2시간", 120), ("1일", 1440), ("90 분", 90),
])
def test_parse_duration_korean_units(text, minutes):
    assert cron.parse_duration(text) == minutes


def test_korean_interval_every_n_minutes():
    got = cron.parse_schedule("30분마다")
    assert got["kind"] == "interval" and got["minutes"] == 30


def test_korean_daily_at_clock():
    got = cron.parse_schedule("매일 09:00")
    assert got["kind"] == "daily" and (got["hour"], got["minute"]) == (9, 0)


def test_korean_weekly_maps_to_cron_expression():
    got = cron.parse_schedule("매주 월요일 09:00")
    assert got["kind"] == "cron" and got["expr"] == "0 9 * * 1"
    nxt = datetime.fromisoformat(
        cron.compute_next_run(got, datetime(2026, 7, 25, 12, 0)))
    assert nxt.weekday() == 0 and (nxt.hour, nxt.minute) == (9, 0)


def test_korean_once_after_duration():
    base = datetime.now()
    got = cron.parse_schedule("30분 후")
    assert got["kind"] == "once"
    when = datetime.fromisoformat(got["run_at"])
    assert timedelta(minutes=29) <= when - base <= timedelta(minutes=31)


@pytest.mark.parametrize("text", ["매일", "매주 09:00", "매일 25:00", "분마다"])
def test_korean_malformed_schedules_rejected(text):
    assert cron.parse_schedule(text) is None


@pytest.mark.parametrize("arg,kind,task", [
    ("30분마다 메일 확인", "interval", "메일 확인"),
    ("매일 09:00 오늘 할 일 정리", "daily", "오늘 할 일 정리"),
    ("매주 월요일 09:00 주간 리뷰", "cron", "주간 리뷰"),
    ("1시간 후 스트레칭", "once", "스트레칭"),
    ("0 9 * * 1 weekly review", "cron", "weekly review"),
    ("every 30m mail", "interval", "mail"),
])
def test_remind_splits_korean_schedule_from_task(arg, kind, task):
    """The /remind splitter must hand the parser the right token count.

    The 3-token Korean weekly form parsed fine standalone but the splitter
    only tried 5/2/1 tokens, so '매주 월요일 09:00 주간 리뷰' fell through.
    """
    from birkin.gateway.core import _split_schedule
    spec, prompt = _split_schedule(arg)
    assert spec is not None and spec["kind"] == kind
    assert prompt == task
