from __future__ import annotations

from datetime import datetime, timedelta, timezone

from birkin import procreg, store


def test_registry_records_generation_session_purpose_and_deadline(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setattr(
        procreg,
        "process_generation",
        lambda pid: f"generation-{pid}",
    )
    deadline = datetime.now(timezone.utc) + timedelta(minutes=5)

    procreg.register(
        4242,
        session_id="computer-use-a",
        purpose="macos-qa-fixture",
        deadline=deadline,
    )

    data = store._read_json(procreg._reg_path(), None)
    assert data["version"] == 2
    assert data["records"] == [
        {
            "pid": 4242,
            "process_generation": "generation-4242",
            "session_id": "computer-use-a",
            "purpose": "macos-qa-fixture",
            "deadline": deadline.isoformat(),
        }
    ]
    procreg.unregister(4242)


def test_reaper_never_kills_reused_pid_generation(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    path = procreg._reg_path(owner=999)
    store._write_json(
        path,
        {
            "version": 2,
            "owner": 999,
            "owner_generation": "owner-old",
            "children": [4242],
            "records": [
                {
                    "pid": 4242,
                    "process_generation": "child-old",
                    "session_id": "computer-use-a",
                    "purpose": "qa",
                    "deadline": None,
                }
            ],
        },
    )
    killed: list[int] = []
    monkeypatch.setattr(
        procreg,
        "process_generation",
        lambda pid: {
            999: "owner-new",
            4242: "child-new",
        }.get(pid),
    )

    result = procreg.reap_orphans(
        alive=lambda pid: pid in {999, 4242},
        kill=killed.append,
    )

    assert result["dead_owners"] == 1
    assert result["killed"] == 0
    assert killed == []
