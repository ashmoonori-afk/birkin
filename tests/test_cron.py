import json
from datetime import datetime

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


def test_load_jobs_rejects_unknown_schedule_kind_without_rewriting():
    path = config.cron_path()
    raw = (
        '[{"schema_version":1,"id":"bad","name":"bad","hour":9,'
        '"minute":0,"type":"prompt","value":"go","enabled":true,'
        '"created":"2026-05-28T08:00:00","last_run":null,'
        '"deliver_chat_id":null,"schedule":{"kind":"weekly",'
        '"display":"weekly"},"next_run":"2026-05-29T09:00:00"}]'
    )
    path.write_text(raw, encoding="utf-8")

    with pytest.raises(cron.CronFormatError, match="schedule.kind"):
        cron.load_jobs()

    assert path.read_text(encoding="utf-8") == raw


def test_load_jobs_rejects_unknown_action_type():
    job = cron.add_job(
        name="ok", hour=9, minute=0, action_type="prompt", value="go"
    )
    job["type"] = "magic"
    config.cron_path().write_text(json.dumps([job]), encoding="utf-8")

    with pytest.raises(cron.CronFormatError, match=r"\.type"):
        cron.load_jobs()


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

    claimed = cron.claim_if_due(job["id"], datetime.now())

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
    cron.add_job(name="morning", hour=9, minute=0, action_type="prompt", value="x")
    before = datetime(2026, 5, 28, 8, 0)   # earlier than 09:00
    after = datetime(2026, 5, 28, 10, 0)   # later than 09:00
    assert cron.due_jobs(before) == []
    assert len(cron.due_jobs(after)) == 1


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
