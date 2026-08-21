from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from birkin.executable_resolution import (
    CommandProbe,
    ExecutableResolver,
    ProbeExecution,
    ProbeFailureKind,
)
from birkin.skills.loader import Skill


@dataclass
class FakeCandidates:
    paths: tuple[str, ...]

    def candidates(self, command: str) -> tuple[str, ...]:
        assert command == "tool"
        return self.paths


@dataclass
class FakeRunner:
    results: dict[str, ProbeExecution]

    def run(self, probe: CommandProbe) -> ProbeExecution:
        return self.results[probe.path]


def _skill(
    tmp_path: Path,
    paths: tuple[str, ...],
    results: dict[str, ProbeExecution],
) -> Skill:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("---\nname: probe\n---\n", encoding="utf-8")
    resolver = ExecutableResolver(FakeCandidates(paths), FakeRunner(results))
    return Skill(
        name="probe",
        description="probe",
        path=skill_file,
        source="extra",
        meta={"prerequisites": {"commands": ["tool"]}},
        _resolver=resolver,
    )


def test_two_identical_skills_compare_equal(tmp_path: Path) -> None:
    skill_file = tmp_path / "SKILL.md"
    skill_file.write_text("body\n", encoding="utf-8")
    attributes = {
        "name": "same",
        "description": "same",
        "path": skill_file,
        "source": "extra",
    }

    assert Skill(**attributes) == Skill(**attributes)


def test_skill_prerequisite_rejects_nonfunctional_shim(tmp_path: Path) -> None:
    shim = str(tmp_path / "tool-shim.exe")
    skill = _skill(
        tmp_path,
        (shim,),
        {shim: ProbeExecution(0, "", "")},
    )

    assert skill.eligible is False
    diagnostics = skill.prerequisite_diagnostics
    assert diagnostics[0].attempts[0].failure_kind is (
        ProbeFailureKind.NON_FUNCTIONAL_SHIM
    )
    assert shim in diagnostics[0].failure_text()


def test_skill_prerequisite_accepts_later_verified_candidate(
    tmp_path: Path,
) -> None:
    shim = str(tmp_path / "tool-shim.exe")
    real = str(tmp_path / "tool-real.exe")
    skill = _skill(
        tmp_path,
        (shim, real),
        {
            shim: ProbeExecution(0, "", ""),
            real: ProbeExecution(0, "tool 1.0", ""),
        },
    )

    assert skill.eligible is True
    assert skill.prerequisite_diagnostics == ()
