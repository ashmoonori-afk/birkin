from __future__ import annotations

from pathlib import Path

from birkin.skills.loader import discover
from birkin.skills.manager import SkillManager
from birkin.skills.validate import validate_skill


ROOT = Path(__file__).parents[1]
SKILLS = ROOT / "skills"


def _catalog() -> tuple[dict, SkillManager]:
    dirs = [(SKILLS, "bundled")]
    return discover(dirs), SkillManager(dirs)


def test_debug_programming_system_loads() -> None:
    catalog, manager = _catalog()
    skill = catalog["debugging"]
    birkin_meta = skill.meta["metadata"]["birkin"]

    assert birkin_meta["provenance"] == "birkin-original"
    assert birkin_meta["protocol"] == [
        "reproduce",
        "pin",
        "hypothesize",
        "experiment",
        "red",
        "root-cause",
        "fix",
        "verify",
        "manual-qa",
        "cleanup",
    ]
    assert "debug-programming" not in catalog
    assert not validate_skill(skill.path, source="bundled").errors
    assert [
        routed.name
        for routed in manager.route(
            "debug a failing program with hypotheses and regression tests"
        )
    ][0] == "debugging"
    assert [
        routed.name
        for routed in manager.route("프로그램 버그를 재현하고 디버깅해줘")
    ][0] == "debugging"


def test_imported_system_rejects_malformed_frontmatter(
    tmp_path: Path,
) -> None:
    skill_md = tmp_path / "malformed" / "SKILL.md"
    skill_md.parent.mkdir()
    skill_md.write_text(
        "---\n"
        "name:\n"
        "description:\n"
        "version: 1.0.0\n"
        "license: MIT\n"
        "---\n\n"
        "# Malformed\n",
        encoding="utf-8",
    )

    report = validate_skill(skill_md, source="bundled")

    assert report.errors == [
        "missing required frontmatter field: 'name'",
        "missing required frontmatter field: 'description'",
        "no '## When to Use' section — agent routing degraded",
    ]
