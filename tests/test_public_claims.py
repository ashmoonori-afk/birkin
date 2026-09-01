"""Public README claims are checked against machine truth, not against prose.

Both READMEs advertise the mandatory runtime dependencies and the size of the
bundled skill catalog. Each is a machine fact: the first lives in
``[project].dependencies``, the second is the number of tracked ``SKILL.md``
files. The claims are parsed structurally - backticked package names and one
bold count inside the single claims paragraph - so rewording stays free while a
wrong package name or a stale count fails.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10
    import tomli as tomllib

_ROOT = Path(__file__).resolve().parent.parent
_READMES = ("README.md", "README.ko.md")
_BACKTICKED: Final[re.Pattern[str]] = re.compile(r"`([^`]+)`")
_BOLD: Final[re.Pattern[str]] = re.compile(r"\*\*([^*]+)\*\*")
_COUNT: Final[re.Pattern[str]] = re.compile(r"(\d+)\D+")
_SNAPSHOT: Final[re.Pattern[str]] = re.compile(r"Snapshot:\s*(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True, slots=True)
class _ClaimTruth:
    """The machine values a claims paragraph is allowed to advertise."""

    dependencies: frozenset[str]
    bundled: frozenset[str]
    skills: int


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AssertionError(f"invalid TOML mapping at {path}")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise AssertionError(f"invalid TOML key at {path}")
        result[key] = item
    return result


def _strings(value: object, path: str) -> list[str]:
    if not isinstance(value, list):
        raise AssertionError(f"invalid TOML string list at {path}")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise AssertionError(f"invalid TOML string list at {path}")
        result.append(item)
    return result


def _normalize(name: str) -> str:
    """PEP 503 normalized distribution name."""
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def _pyproject() -> tuple[list[str], list[str]]:
    with (_ROOT / "pyproject.toml").open("rb") as handle:
        manifest = _mapping(tomllib.load(handle), "root")
    project = _mapping(manifest.get("project"), "project")
    tool = _mapping(manifest.get("tool"), "tool")
    hatch = _mapping(tool.get("hatch"), "tool.hatch")
    build = _mapping(hatch.get("build"), "tool.hatch.build")
    targets = _mapping(build.get("targets"), "tool.hatch.build.targets")
    wheel = _mapping(targets.get("wheel"), "tool.hatch.build.targets.wheel")
    return (
        _strings(project.get("dependencies"), "project.dependencies"),
        _strings(wheel.get("packages"), "tool.hatch.build.targets.wheel.packages"),
    )


def _live_truth() -> _ClaimTruth:
    requirements, packages = _pyproject()
    return _ClaimTruth(
        dependencies=frozenset(
            _normalize(re.split(r"[<>=!~;\[ ]", item, maxsplit=1)[0])
            for item in requirements
        ),
        bundled=frozenset(_normalize(item) for item in packages),
        skills=_tracked_skill_count(),
    )


def _tracked_skill_count() -> int:
    """Bundled skills the repository actually tracks."""
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", "skills"],
        cwd=_ROOT,
        capture_output=True,
        check=True,
    )
    entries = completed.stdout.decode("utf-8").split("\0")
    return sum(1 for entry in entries if entry.endswith("/SKILL.md"))


def _claims_paragraph(text: str) -> str:
    """The one paragraph that carries both a package claim and a bold count."""
    paragraphs = [
        block
        for block in re.split(r"\n\s*\n", text)
        if "`" in block and any(_COUNT.fullmatch(bold) for bold in _BOLD.findall(block))
    ]
    assert len(paragraphs) == 1, (
        f"expected exactly 1 claims paragraph, found {len(paragraphs)}"
    )
    return paragraphs[0]


def _claimed_skill_count(paragraph: str) -> int:
    counts = [
        int(match.group(1))
        for bold in _BOLD.findall(paragraph)
        if (match := _COUNT.fullmatch(bold))
    ]
    assert len(counts) == 1, f"expected exactly 1 bold count claim, found {len(counts)}"
    return counts[0]


def _claim_gaps(paragraph: str, truth: _ClaimTruth) -> list[str]:
    """ASCII descriptions of every machine value the paragraph gets wrong."""
    claimed = frozenset(
        _normalize(token) for token in _BACKTICKED.findall(paragraph)
    ) - truth.bundled
    gaps = [f"missing dependency claim: {name}" for name in sorted(truth.dependencies - claimed)]
    gaps += [
        f"undeclared dependency claim: {name}" for name in sorted(claimed - truth.dependencies)
    ]
    claimed_skills = _claimed_skill_count(paragraph)
    if claimed_skills != truth.skills:
        gaps.append(f"skill count claim {claimed_skills} != tracked {truth.skills}")
    return gaps


@pytest.mark.parametrize("name", _READMES)
def test_readme_claims_match_declared_dependencies_and_tracked_skills(name: str) -> None:
    """Given the manifest and the tracked catalog, each README claims both truthfully."""
    truth = _live_truth()
    assert truth.skills > 0, "git tracks no bundled skills"

    paragraph = _claims_paragraph((_ROOT / name).read_text(encoding="utf-8"))

    assert _claim_gaps(paragraph, truth) == []


def test_claim_gaps_name_a_missing_dependency_and_a_stale_count() -> None:
    """Given a synthetic paragraph short one dependency and stale by two skills."""
    truth = _ClaimTruth(
        dependencies=frozenset({"pydantic", "psutil"}),
        bundled=frozenset({"birkin-mnemosyne"}),
        skills=7,
    )
    paragraph = (
        "The runtime needs `psutil` only. `birkin_mnemosyne` ships inside the wheel. "
        "The repository currently bundles **5 skills**."
    )

    gaps = _claim_gaps(paragraph, truth)

    assert gaps == [
        "missing dependency claim: pydantic",
        "skill count claim 5 != tracked 7",
    ]
    assert all(gap.isascii() for gap in gaps)


def test_claim_gaps_name_a_dependency_the_manifest_never_declares() -> None:
    """Given a synthetic paragraph advertising a package that is not a dependency."""
    truth = _ClaimTruth(
        dependencies=frozenset({"psutil"}),
        bundled=frozenset({"birkin-mnemosyne"}),
        skills=7,
    )
    paragraph = "It needs `psutil` and `requests`. It bundles **7 skills**."

    gaps = _claim_gaps(paragraph, truth)

    assert gaps == ["undeclared dependency claim: requests"]


def test_comparison_keeps_one_dated_snapshot_marker() -> None:
    """Given the comparison doc, its head carries one parseable snapshot date."""
    head = (_ROOT / "docs" / "COMPARISON.md").read_text(encoding="utf-8").splitlines()[:5]

    stamped = [match.group(1) for match in map(_SNAPSHOT.search, head) if match]

    assert len(stamped) == 1, "docs/COMPARISON.md needs one snapshot marker in its first 5 lines"
    assert date.fromisoformat(stamped[0]).isoformat() == stamped[0]
