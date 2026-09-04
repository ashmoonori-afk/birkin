from __future__ import annotations

import json
from pathlib import Path
from typing import cast, final

import pytest

from birkin.computer_use.models import FocusSnapshot
from scripts.qa import computer_use_macos_dogfood as dogfood


def result(scenario: str, outcome: str, *, mandatory: bool = True) -> dict[str, object]:
    return {
        "scenario_id": scenario,
        "result": outcome,
        "mandatory": mandatory,
    }


def test_permissioned_required_rejects_mandatory_skip() -> None:
    records = [result(scenario, "passed") for scenario in dogfood.REQUIRED_SCENARIOS]
    records[-1] = result(str(records[-1]["scenario_id"]), "skipped")

    assert dogfood.accepted("permissioned-required", records) is False


def test_permissioned_required_rejects_failed_effect() -> None:
    records = [result(scenario, "passed") for scenario in dogfood.REQUIRED_SCENARIOS]
    records = [
        result("confirmed-mutation", "failed")
        if item["scenario_id"] == "confirmed-mutation"
        else item
        for item in records
    ]

    assert dogfood.accepted("permissioned-required", records) is False


def test_ledger_is_jsonl_not_a_json_array(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    dogfood.append_record(ledger, result("one", "passed"))
    dogfood.append_record(ledger, result("two", "limited", mandatory=False))

    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    decoded = [cast(object, json.loads(line)) for line in lines]
    assert [cast(dict[str, object], item)["scenario_id"] for item in decoded] == [
        "one",
        "two",
    ]
    with pytest.raises(json.JSONDecodeError):
        parsed = cast(object, json.loads(ledger.read_text(encoding="utf-8")))
        raise AssertionError(f"ledger unexpectedly decoded as {parsed!r}")


@final
class FakeProcess:
    def __init__(self) -> None:
        self.pid = 4312
        self.returncode: int | None = None

    def wait(self, timeout: float | None = None) -> int:
        assert timeout == 10
        self.returncode = -15
        return -15


@final
class FakeCleanupBackend:
    def __init__(self, focus: FocusSnapshot) -> None:
        self.focus = focus

    def release_inputs(self) -> tuple[str, ...]:
        return ()

    def focus_state(self) -> FocusSnapshot:
        return self.focus

    def can_restore_focus(self, snapshot: FocusSnapshot) -> bool:
        return snapshot == self.focus

    def restore_focus(self, snapshot: FocusSnapshot) -> bool:
        return snapshot == self.focus


@final
class FakeCleanupRuntime:
    def __init__(self) -> None:
        self.killed: list[int] = []
        self.unregistered: list[int] = []

    def kill(self, process: dogfood.FixtureProcess) -> None:
        self.killed.append(process.pid)

    def unregister(self, pid: int) -> None:
        self.unregistered.append(pid)

    def pid_alive(self, pid: int) -> bool:
        assert pid == 4312
        return False


def test_cleanup_kills_fixture_unregisters_and_confirms_focus() -> None:
    process = FakeProcess()
    focus = FocusSnapshot(12, "34", (100, 200), None)
    runtime = FakeCleanupRuntime()

    cleanup = dogfood.cleanup_fixture(
        process,
        FakeCleanupBackend(focus),
        focus,
        registration_attempted=True,
        runtime=runtime,
    )

    assert runtime.killed == [4312]
    assert runtime.unregistered == [4312]
    assert cleanup["alive"] is False
    assert cleanup["focus_preserved"] is True
    assert cleanup["ok"] is True


def test_hosted_acceptance_requires_machine_checked_limitation() -> None:
    records = [
        result("fixture-readiness", "passed"),
        result("cleanup", "passed"),
    ]
    assert dogfood.accepted("hosted", records) is False

    records.append(result("hosted-limitations", "passed"))
    assert dogfood.accepted("hosted", records) is True


@pytest.mark.parametrize(
    ("effect", "expected"),
    [("suspected_noop", False), ("confirmed", True)],
)
def test_permissioned_mutation_requires_confirmed_effect_and_receipt(
    effect: str,
    expected: bool,
) -> None:
    mutation: dict[str, object] = {
        "ok": True,
        "effect": effect,
        "receipt_ref": "receipt",
        "focus": {"preserved": True},
    }

    assert dogfood.mutation_confirmed(mutation) is expected
