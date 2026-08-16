import json
from datetime import datetime, timedelta

import pytest

from birkin import config, cron, store


def test_add_and_load_job():
    job = cron.add_job(name="digest", hour=9, minute=0, action_type="prompt", value="go")
    jobs = cron.load_jobs()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job["id"]
    assert jobs[0]["name"] == "digest"
    assert jobs[0]["schema_version"] == cron.CRON_SCHEMA_VERSION == 1
    assert jobs[0]["schedule"]["kind"] == "daily"


def test_load_jobs_migrates_legacy_daily_record():
    path = config.cron_path()
    path.write_text(
        '[{"id":"legacy","name":"old","hour":9,"minute":0,'
        '"type":"prompt","value":"go","enabled":true,'
        '"created":"2026-05-28T08:00:00","last_run":null,'
        '"deliver_chat_id":null}]',
        encoding="utf-8",
    )

    [job] = cron.load_jobs()

    assert job["schema_version"] == 1
    assert job["schedule"] == {
        "kind": "daily",
        "hour": 9,
        "minute": 0,
        "display": "09:00",
    }
    assert json.loads(path.read_text(encoding="utf-8"))[0] == job


def test_load_jobs_skips_unknown_schedule_kind_without_rewriting(capsys):
    path = config.cron_path()
    raw = (
        '[{"schema_version":1,"id":"bad","name":"bad","hour":9,'
        '"minute":0,"type":"prompt","value":"go","enabled":true,'
        '"created":"2026-05-28T08:00:00","last_run":null,'
        '"deliver_chat_id":null,"schedule":{"kind":"weekly",'
        '"display":"weekly"},"next_run":"2026-05-29T09:00:00"}]'
    )
    path.write_text(raw, encoding="utf-8")

    assert cron.load_jobs() == []                       # skipped, not fatal
    assert path.read_text(encoding="utf-8") == raw      # and not rewritten
    assert "schedule.kind" in capsys.readouterr().out

    with pytest.raises(cron.CronFormatError, match="schedule.kind"):
        cron.save_jobs(json.loads(raw))                 # writers stay strict


def test_load_jobs_skips_unknown_action_type(capsys):
    good = cron.add_job(
        name="ok", hour=9, minute=0, action_type="prompt", value="go"
    )
    bad = {**good, "id": "magical", "type": "magic"}
    config.cron_path().write_text(json.dumps([good, bad]), encoding="utf-8")

    assert [job["id"] for job in cron.load_jobs()] == [good["id"]]
    assert ".type" in capsys.readouterr().out

    with pytest.raises(cron.CronFormatError, match=r"\.type"):
        cron.save_jobs([bad])


def test_load_jobs_quarantines_non_string_delivery_channel(capsys):
    good = cron.add_job(name="good")
    bad = {**good, "id": "bad-channel", "deliver_channel": []}
    config.cron_path().write_text(json.dumps([good, bad]), encoding="utf-8")

    assert [job["id"] for job in cron.load_jobs()] == [good["id"]]
    assert ".deliver_channel" in capsys.readouterr().out

    with pytest.raises(cron.CronFormatError, match=r"\.deliver_channel"):
        cron.save_jobs([bad])


def test_load_jobs_survives_a_file_that_is_not_a_list(capsys):
    config.cron_path().write_text('{"oops": true}', encoding="utf-8")

    assert cron.load_jobs() == []
    assert "cron.json" in capsys.readouterr().out


def test_load_jobs_drops_hand_added_unknown_fields(capsys):
    good = cron.add_job(
        name="ok", hour=9, minute=0, action_type="prompt", value="go"
    )
    config.cron_path().write_text(
        json.dumps([{**good, "notes": "hand-added"}]), encoding="utf-8"
    )

    [loaded] = cron.load_jobs()

    assert loaded["id"] == good["id"]
    assert "notes" not in loaded
    assert "notes" in capsys.readouterr().out


def test_legacy_migration_rereads_after_acquiring_lock(
    monkeypatch,
) -> None:
    path = config.cron_path()
    legacy = {
        "id": "legacy",
        "name": "old",
        "hour": 9,
        "minute": 0,
        "type": "prompt",
        "value": "go",
        "enabled": True,
        "created": "2026-05-28T08:00:00",
        "last_run": None,
        "deliver_chat_id": None,
    }
    concurrent = {
        **legacy,
        "id": "concurrent",
        "name": "new",
    }
    path.write_text(json.dumps([legacy]), encoding="utf-8")
    real_lock = store.file_lock

    class ConcurrentWriterLock:
        def __init__(self):
            self._lock = real_lock(path)

        def __enter__(self):
            path.write_text(
                json.dumps([legacy, concurrent]),
                encoding="utf-8",
            )
            return self._lock.__enter__()

        def __exit__(self, *args):
            return self._lock.__exit__(*args)

    monkeypatch.setattr(
        store, "file_lock", lambda _path: ConcurrentWriterLock()
    )

    jobs = cron.load_jobs()

    assert [job["id"] for job in jobs] == ["legacy", "concurrent"]


def test_cron_schema_declares_exact_schedule_variants() -> None:
    import importlib.resources

    schema = json.loads(
        importlib.resources.files("birkin").joinpath(
            "schemas/cron-job-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    variants = schema["properties"]["schedule"]["oneOf"]

    assert {
        variant["properties"]["kind"]["const"] for variant in variants
    } == {"daily", "interval", "once", "cron"}
    assert {
        tuple(variant["required"]) for variant in variants
    } == {
        ("kind", "display", "hour", "minute"),
        ("kind", "display", "minutes"),
        ("kind", "display", "run_at"),
        ("kind", "display", "expr"),
    }


def test_claim_returns_current_persisted_snapshot() -> None:
    job = cron.add_job(
        name="before",
        hour=0,
        minute=0,
        action_type="shell",
        value="old",
    )
    jobs = cron.load_jobs()
    jobs[0]["name"] = "after"
    jobs[0]["value"] = "new"
    cron.save_jobs(jobs)

    claimed = cron.claim_if_due(
        job["id"], datetime.fromisoformat(jobs[0]["next_run"])
    )

    assert claimed is not None
    assert claimed["name"] == "after"
    assert claimed["value"] == "new"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda job: job.update(deliver_chat_id=7),
        lambda job: job.update(hour=24),
        lambda job: job.update(surprise=True),
        lambda job: job.update(
            type="monitor",
            monitor_url=None,
            monitor_script=None,
            max_bytes=1024,
        ),
    ],
)
def test_versioned_cron_records_enforce_complete_contract(mutate) -> None:
    job = cron.add_job(
        name="strict",
        hour=9,
        minute=0,
        action_type="prompt",
        value="go",
    )
    mutate(job)

    with pytest.raises(cron.CronFormatError):
        cron.save_jobs([job])


def test_schedule_rejects_missing_display_and_extra_fields() -> None:
    job = cron.add_job(
        name="strict schedule",
        hour=9,
        minute=0,
        action_type="prompt",
        value="go",
    )
    del job["schedule"]["display"]
    with pytest.raises(cron.CronFormatError):
        cron.save_jobs([job])

    job["schedule"]["display"] = "09:00"
    job["schedule"]["surprise"] = True
    with pytest.raises(cron.CronFormatError):
        cron.save_jobs([job])


def test_non_monitor_rejects_monitor_only_fields() -> None:
    job = cron.add_job(
        name="strict action",
        hour=9,
        minute=0,
        action_type="prompt",
        value="go",
    )
    job["monitor_url"] = "https://example.com"

    with pytest.raises(cron.CronFormatError):
        cron.save_jobs([job])


def test_empty_prompt_value_remains_valid() -> None:
    job = cron.add_job(name="empty")

    assert job["value"] == ""
    assert cron.load_jobs()[0]["value"] == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("monitor_url", 7),
        ("monitor_script", ["echo", "bad"]),
    ],
)
def test_monitor_sources_require_strings(field, value) -> None:
    job = cron.add_job(
        name="monitor",
        action_type="monitor",
        monitor_url="https://example.com",
    )
    job[field] = value

    with pytest.raises(cron.CronFormatError):
        cron.save_jobs([job])


def test_add_monitor_job_schema_clamps_max_bytes():
    job = cron.add_job(
        name="watch", action_type="monitor", value="summarize the change",
        monitor_url="https://example.test/feed", max_bytes=999_999,
    )

    assert job["monitor_url"] == "https://example.test/feed"
    assert job["monitor_script"] is None
    assert job["max_bytes"] == 256 * 1024


def test_monitor_job_rejects_multiple_sources():
    with pytest.raises(ValueError, match="at most one"):
        cron.add_job(
            name="watch", action_type="monitor", value="report",
            monitor_url="https://example.test", monitor_script="echo hi",
        )


def test_due_jobs_respects_time():
    job = cron.add_job(name="morning", hour=9, minute=0,
                       action_type="prompt", value="x")
    armed = datetime.fromisoformat(job["next_run"])
    assert cron.due_jobs(armed - timedelta(minutes=1)) == []
    assert len(cron.due_jobs(armed)) == 1


def test_daily_job_waits_for_its_armed_next_run():
    """A daily job created after today's clock time fires tomorrow, not now."""
    now = datetime.now()
    past = now - timedelta(minutes=2)
    job = cron.add_job(
        name="daily late",
        schedule={"kind": "daily", "hour": past.hour, "minute": past.minute,
                  "display": f"{past.hour:02d}:{past.minute:02d}"},
    )

    assert datetime.fromisoformat(job["next_run"]) > now
    assert cron.due_jobs(now) == []
    assert cron.claim_if_due(job["id"], now) is None


def test_mark_ran_excludes_same_day_and_is_immutable():
    job = cron.add_job(name="m", hour=9, minute=0, action_type="prompt", value="x")
    original = cron.load_jobs()[0]
    cron.mark_ran(job["id"])
    after = datetime(2026, 5, 28, 10, 0)
    # already ran today -> not due
    assert cron.due_jobs(after) == []
    # mark_ran replaces, not mutates: the previously-loaded dict is unchanged
    assert original["last_run"] is None


def test_disabled_job_not_due():
    cron.add_job(name="off", hour=1, minute=0, action_type="prompt", value="x",
                 enabled=False)
    assert cron.due_jobs(datetime(2026, 5, 28, 23, 0)) == []


def test_remove_job():
    job = cron.add_job(name="z", hour=1, minute=0, action_type="prompt", value="x")
    assert cron.remove_job(job["id"]) is True
    assert cron.load_jobs() == []
    assert cron.remove_job("nope") is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda: cron.add_job(name="busy", hour=1, minute=2,
                             action_type="prompt", value="x"),
        lambda: cron.remove_job("keep"),
        lambda: cron.mark_ran("keep"),
    ],
    ids=["add_job", "remove_job", "mark_ran"],
)
def test_busy_lock_preserves_each_cron_mutation(monkeypatch, mutation):
    path = config.cron_path()
    path.write_bytes(b'[{"id":"keep","last_run":null}]')
    before = (path.exists(), path.read_bytes())

    class BusyLock:
        def __enter__(self):
            raise store.FileLockTimeout("busy")

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(store, "file_lock", lambda _path: BusyLock())

    with pytest.raises(store.FileLockTimeout) as caught:
        mutation()

    assert type(caught.value) is store.FileLockTimeout
    assert (path.exists(), path.read_bytes()) == before


def test_cron_claim_returns_false_on_lock_timeout(monkeypatch):
    path = config.cron_path()
    path.write_bytes(b'[{"id":"keep","last_run":null}]')
    before = (path.exists(), path.read_bytes())

    class BusyLock:
        def __enter__(self):
            raise store.FileLockTimeout("busy")

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(store, "file_lock", lambda _path: BusyLock())

    assert cron.claim_if_due("keep") is None
    assert (path.exists(), path.read_bytes()) == before
