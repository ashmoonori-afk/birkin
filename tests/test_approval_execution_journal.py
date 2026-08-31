from __future__ import annotations

import json
import multiprocessing
import os
import sys
import uuid
from pathlib import Path

from multiprocessing.connection import Listener
from multiprocessing.synchronize import Barrier as BarrierType

import pytest

from birkin import approval_execution, approval_execution_recovery, store
from birkin.approval_execution_helper import helper_argv
from birkin.approval_execution_journal import ExecutionJournal
from birkin.approval_execution_state import JournalPhase


def _recover_at_barrier(home: str, approval_id: str, barrier: BarrierType) -> None:
    os.environ["BIRKIN_HOME"] = home
    barrier.wait()
    approval_execution_recovery.recover_one(approval_id, wait=True)


def _approve_parent(home: str, approval_id: str) -> None:
    os.environ["BIRKIN_HOME"] = home
    approval_execution.approve(approval_id)


def _executing(tmp_path: Path) -> tuple[str, ExecutionJournal]:
    record = store.add_pending(
        category="memory",
        title="sealed",
        description="",
        payload={"value": "sealed"},
        origin="test",
    )
    approval_id = str(record["id"])
    store.resolve_pending(approval_id, "executing")
    current = store.get_pending(approval_id)
    assert current is not None
    journal = ExecutionJournal(approval_id)
    journal.arm(
        approval_execution._authority_digest(current), "memory", {"value": "sealed"}
    )
    journal.ready()
    return approval_id, journal


def test_attempt_is_fsynced_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: sealed authority with a ready execution journal.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    _approval_id, journal = _executing(tmp_path)

    # When: the helper crosses the external dispatch boundary.
    journal.commit_attempt(owner_pid=os.getpid())

    # Then: durable state already proves that Birkin spent its one invocation.
    assert journal.load().phase is JournalPhase.ATTEMPT_COMMITTED


def test_fsync_failure_blocks_attempt_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a ready journal whose durable flush fails.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    _approval_id, journal = _executing(tmp_path)
    monkeypatch.setattr(
        os, "fsync", lambda _descriptor: (_ for _ in ()).throw(OSError("disk"))
    )

    # When / Then: committing authority fails before a dispatcher can run.
    with pytest.raises(OSError, match="disk"):
        journal.commit_attempt(owner_pid=os.getpid())


def test_tampered_journal_freezes_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one byte of sealed authority is changed after persistence.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    approval_id, journal = _executing(tmp_path)
    raw = journal.path.read_text(encoding="utf-8")
    journal.path.write_text(raw.replace("sealed", "forged"), encoding="utf-8")

    # When: startup recovery reads the journal.
    result = approval_execution_recovery.recover_one(approval_id)

    # Then: execution is frozen and never dispatched.
    assert result == {"ok": False, "error": "approval execution journal was tampered"}
    record = store.get_pending(approval_id)
    assert record is not None
    assert record["status"] == "execution_frozen"


def test_dead_committed_owner_becomes_unknown_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: Birkin committed its invocation and the owner no longer exists.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    approval_id, journal = _executing(tmp_path)
    journal.commit_attempt(owner_pid=2**30)

    # When: recovery observes the dead owner.
    result = approval_execution_recovery.recover_one(approval_id)

    # Then: the action is explicitly unknown and the journal is terminal.
    assert result == {
        "ok": False,
        "error": "action outcome is unknown",
        "recoverable": False,
    }
    assert journal.load().phase is JournalPhase.ACTION_OUTCOME_UNKNOWN


def test_legacy_committed_event_without_generation_is_conservatively_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an older attempt event names a live PID but has no generation.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    approval_id, journal = _executing(tmp_path)
    journal.commit_attempt(owner_pid=os.getpid())
    monkeypatch.setattr(
        approval_execution_recovery.procreg,
        "pid_alive",
        lambda _pid: True,
    )
    monkeypatch.setattr(
        approval_execution_recovery.procreg,
        "process_generation",
        lambda pid: f"{pid}:current",
    )

    # When: recovery cannot bind that legacy PID to its original process.
    result = approval_execution_recovery.recover_one(approval_id)

    # Then: it never replays and records explicit unknown outcome.
    assert result == {
        "ok": False,
        "error": "action outcome is unknown",
        "recoverable": False,
    }
    assert journal.load().phase is JournalPhase.ACTION_OUTCOME_UNKNOWN


def test_reused_live_pid_marks_committed_attempt_unknown_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the committed helper PID was reused by a different process generation.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    approval_id, journal = _executing(tmp_path)
    journal.commit_attempt(
        owner_pid=4242,
        owner_generation="4242:original",
    )
    monkeypatch.setattr(
        approval_execution_recovery.procreg,
        "pid_alive",
        lambda _pid: True,
    )
    monkeypatch.setattr(
        approval_execution_recovery.procreg,
        "process_generation",
        lambda _pid: "4242:reused",
    )

    # When: recovery checks both PID liveness and generation identity.
    result = approval_execution_recovery.recover_one(approval_id)

    # Then: Birkin treats the original owner as dead and never replays.
    assert result == {
        "ok": False,
        "error": "action outcome is unknown",
        "recoverable": False,
    }
    assert journal.load().phase is JournalPhase.ACTION_OUTCOME_UNKNOWN


def test_helper_hard_exit_before_attempt_is_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a real helper is forced to die before spending invocation authority.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setenv("BIRKIN_APPROVAL_HELPER_TEST_EXIT", "before_attempt")
    record = store.add_pending(
        category="memory", title="exit", description="", payload={}, origin="test"
    )

    # When: approval launches and waits for that helper.
    first = approval_execution.approve(str(record["id"]))
    monkeypatch.delenv("BIRKIN_APPROVAL_HELPER_TEST_EXIT")
    recovered = approval_execution_recovery.recover_one(str(record["id"]), wait=True)

    # Then: only the uncommitted helper is replaced and the action completes.
    assert first == {"ok": False, "error": "approval helper exited with status 86"}
    assert recovered == {
        "ok": True,
        "result": "(memory is applied directly by the agent)",
    }


@pytest.mark.skipif(os.name != "nt", reason="Windows parent/helper kill contract")
def test_parent_hard_exit_after_action_start_keeps_helper_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an action reports exact start/effect events over a named pipe.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    address = rf"\\.\pipe\birkin-approval-{uuid.uuid4().hex}"
    effect = tmp_path / "parent-killed-effect.txt"
    code = (
        "from multiprocessing.connection import Client;from pathlib import Path;"
        f"c=Client({address!r},family='AF_PIPE');c.send('started');c.recv();"
        f"Path({str(effect)!r}).write_text('once');c.send('effect');c.recv()"
    )
    command = f'"{sys.executable}" -c "{code}"'
    record = store.add_pending(
        category="shell",
        title="parent kill",
        description="",
        payload={"command": command, "cwd": str(tmp_path)},
        origin="test",
    )
    context = multiprocessing.get_context("spawn")
    parent = context.Process(
        target=_approve_parent,
        args=(str(tmp_path), str(record["id"])),
    )

    # When: the parent dies only after the helper's action has started.
    with Listener(address=address, family="AF_PIPE") as listener:
        parent.start()
        with listener.accept() as signal:
            assert signal.recv() == "started"
            parent.terminate()
            parent.join(timeout=30)
            signal.send("continue")
            assert signal.recv() == "effect"
            signal.send("finish")
    with store.file_lock(
        tmp_path / "pending" / f"{record['id']}.json",
        timeout=30,
    ):
        projected = store.get_pending(str(record["id"]))

    # Then: the independent helper records known success exactly once.
    assert parent.exitcode is not None and parent.exitcode != 0
    assert effect.read_text(encoding="utf-8") == "once"
    assert projected is not None
    assert projected["status"] == "approved"
    assert ExecutionJournal(str(record["id"])).load().phase is JournalPhase.SUCCEEDED


def test_twenty_recoverers_race_one_helper_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: twenty real recoverers released on one process barrier.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    approval_id, journal = _executing(tmp_path)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(20)
    processes = [
        context.Process(
            target=_recover_at_barrier,
            args=(str(tmp_path), approval_id, barrier),
        )
        for _index in range(20)
    ]

    # When: every recoverer races the same ready authority.
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=60)

    # Then: all recoverers exit and exactly one attempt crosses Birkin's seam.
    assert all(process.exitcode == 0 for process in processes)
    assert journal.load().phase is JournalPhase.SUCCEEDED
    events = [json.loads(line) for line in journal.path.read_text().splitlines()]
    attempts = [event for event in events if event.get("kind") == "attempt_committed"]
    assert len(attempts) == 1
    assert isinstance(attempts[0].get("owner_generation"), str)


def test_helper_hard_exit_after_effect_becomes_unknown_without_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a real shell action writes one effect before its helper hard-exits.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setenv(
        "BIRKIN_APPROVAL_HELPER_TEST_EXIT", "after_effect_before_receipt"
    )
    effect = tmp_path / "effect.txt"
    command = (
        f'"{sys.executable}" -c "from pathlib import Path;'
        f"Path(r'{effect}').write_text('once')\""
    )
    record = store.add_pending(
        category="shell",
        title="effect",
        description="",
        payload={"command": command, "cwd": str(tmp_path)},
        origin="test",
    )

    # When: the effect returns but the helper dies before its terminal receipt.
    first = approval_execution.approve(str(record["id"]))
    monkeypatch.delenv("BIRKIN_APPROVAL_HELPER_TEST_EXIT")
    recovered = approval_execution_recovery.recover_one(str(record["id"]))

    # Then: Birkin never invokes it again and reports explicit ambiguity.
    assert first == {"ok": False, "error": "approval helper exited with status 87"}
    assert recovered == {
        "ok": False,
        "error": "action outcome is unknown",
        "recoverable": False,
    }
    assert effect.read_text(encoding="utf-8") == "once"


def test_normal_and_frozen_helper_argv_are_shell_free() -> None:
    # Given: source and frozen executable layouts.
    token = "b" * 64

    # When: hidden helper argv is selected.
    normal = helper_argv("0123456789ab", token, executable=sys.executable, frozen=False)
    frozen = helper_argv("0123456789ab", token, executable="Birkin.exe", frozen=True)

    # Then: both are explicit argv with no shell command string.
    assert normal == (
        sys.executable,
        "-m",
        "birkin",
        "_approval-helper",
        "0123456789ab",
        token,
    )
    assert frozen == ("Birkin.exe", "_approval-helper", "0123456789ab", token)


def test_legacy_executing_receipt_migrates_without_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the previous receipt-before-projection format.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    record = store.add_pending(
        category="memory", title="legacy", description="", payload={}, origin="test"
    )
    approval_id = str(record["id"])
    store.resolve_pending(approval_id, "executing")
    current = store.get_pending(approval_id)
    assert current is not None
    store.write_action_receipt(
        approval_id,
        {
            "version": 1,
            "status": "action_committed",
            "approval_id": approval_id,
            "authority_digest": approval_execution._authority_digest(current),
            "result": "legacy result",
        },
    )

    # When: current startup recovery migrates it.
    result = approval_execution_recovery.recover_one(approval_id)

    # Then: only projection occurs and permanent journal evidence is terminal.
    assert result == {"ok": True, "result": "legacy result"}
    assert ExecutionJournal(approval_id).load().phase is JournalPhase.SUCCEEDED
    projected = store.get_pending(approval_id)
    assert projected is not None
    assert projected["action_receipt"] == "legacy result"


def test_legacy_executing_without_receipt_migrates_to_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: legacy executing state has no proof of its external outcome.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    record = store.add_pending(
        category="memory",
        title="legacy unknown",
        description="",
        payload={},
        origin="test",
    )
    approval_id = str(record["id"])
    store.resolve_pending(approval_id, "executing")

    # When: startup recovery migrates the ambiguous legacy state.
    result = approval_execution_recovery.recover_one(approval_id)

    # Then: it is never replayed and is explicitly unknown.
    assert result == {
        "ok": False,
        "error": "action outcome is unknown",
        "recoverable": False,
    }
    assert (
        ExecutionJournal(approval_id).load().phase
        is JournalPhase.ACTION_OUTCOME_UNKNOWN
    )


def test_malformed_incomplete_journal_freezes_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a torn final JSONL write.
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    approval_id, journal = _executing(tmp_path)
    journal.path.write_text(json.dumps({"version": 1}), encoding="utf-8")

    # When / Then: recovery freezes rather than guessing or replaying.
    result = approval_execution_recovery.recover_one(approval_id)
    assert result == {
        "ok": False,
        "error": "approval execution journal has an incomplete line",
    }
