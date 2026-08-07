from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

from birkin.skills.guard import scan_skill
from birkin.skills.loader import discover
from birkin.skills.manager import SkillManager
from birkin.skills.validate import validate_skill


ROOT = Path(__file__).parents[1]
SKILLS = ROOT / "skills"
REPORT = ROOT / "docs" / "frontend-debug-systems-research.html"
FRONTEND_SKILL = SKILLS / "software-development" / "frontend-system-design"
NOTICE = ROOT / "NOTICE"
PYPROJECT = ROOT / "pyproject.toml"
UPSTREAM_SHA = "ca56b546e5f12c408a2e75b2499264aacba99065"


class _ReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.active_manifest = False
        self.manifest_parts: list[str] = []
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attr_map = dict(attrs)
        self.tags.append((tag, attr_map))
        if tag == "pre" and attr_map.get("id") == "research-manifest":
            self.active_manifest = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre" and self.active_manifest:
            self.active_manifest = False

    def handle_data(self, data: str) -> None:
        if self.active_manifest:
            self.manifest_parts.append(data)


def _catalog() -> tuple[dict, SkillManager]:
    dirs = [(SKILLS, "bundled")]
    return discover(dirs), SkillManager(dirs)


def _toml_section(text: str, name: str) -> str:
    marker = f"[{name}]"
    lines = text.splitlines()
    start = lines.index(marker) + 1
    end = next(
        (
            index
            for index in range(start, len(lines))
            if lines[index].startswith("[")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_research_html_embeds_machine_manifest() -> None:
    parser = _ReportParser()
    parser.feed(REPORT.read_text(encoding="utf-8"))
    manifest = json.loads("".join(parser.manifest_parts))

    assert manifest == {
        "schemaVersion": 1,
        "reportId": "frontend-debug-systems-port",
        "generatedOn": "2026-08-07",
        "upstream": {
            "repository": "https://github.com/devkodeio/frontend-system-design",
            "revision": UPSTREAM_SHA,
            "license": "MIT",
            "normativeArtifact": "README.md",
            "treeEntries": 4,
            "commitCount": 19,
        },
        "coverage": {
            "readmeSections": 34,
            "detailedSections": 27,
            "bullets": 210,
            "externalLinks": 36,
        },
        "systems": [
            {
                "id": "frontend-system-design",
                "provenance": "devkode-adaptation",
            },
            {
                "id": "debugging",
                "provenance": "birkin-original",
            },
        ],
        "constraints": {
            "activeContent": False,
            "remoteAssets": False,
            "pdfRedistributed": False,
        },
    }
    assert sum(
        attrs.get("data-source-id") is not None for _, attrs in parser.tags
    ) == 36
    assert not {
        "script",
        "iframe",
        "object",
        "embed",
    }.intersection(tag for tag, _ in parser.tags)
    assert not [
        (tag, name)
        for tag, attrs in parser.tags
        for name in attrs
        if name.startswith("on")
    ]
    assert not [
        value
        for _, attrs in parser.tags
        for name, value in attrs.items()
        if name == "src" and value and value.startswith(("http://", "https://"))
    ]


def test_frontend_system_design_skill_loads() -> None:
    catalog, manager = _catalog()
    skill = catalog["frontend-system-design"]
    provenance = skill.meta["metadata"]["birkin"]["provenance"]

    assert provenance == {
        "source": "https://github.com/devkodeio/frontend-system-design",
        "revision": UPSTREAM_SHA,
        "license": "MIT",
        "adaptation": "modified-for-birkin",
    }
    assert not validate_skill(skill.path, source="bundled").errors
    assert [
        routed.name
        for routed in manager.route(
            "design frontend architecture for a large web application"
        )
    ][0] == "frontend-system-design"
    assert [
        routed.name
        for routed in manager.route("프론트엔드 시스템 설계를 해줘")
    ][0] == "frontend-system-design"
    assert "frontend-system-design" not in {
        routed.name for routed in manager.route("debug a failing Python program")
    }
    scan = scan_skill(FRONTEND_SKILL, source="builtin")
    assert scan.verdict == "safe"
    assert not {
        finding.severity
        for finding in scan.findings
        if finding.severity in {"high", "critical"}
    }


def test_attribution_and_packaging_contract() -> None:
    notice = NOTICE.read_text(encoding="utf-8")
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    sdist = _toml_section(pyproject, "tool.hatch.build.targets.sdist")
    wheel_files = _toml_section(
        pyproject,
        "tool.hatch.build.targets.wheel.force-include",
    )

    assert "Copyright (c) 2022 Devkode.io" in notice
    assert UPSTREAM_SHA in notice
    assert (
        "skills/software-development/frontend-system-design/SKILL.md" in notice
    )
    assert '"docs"' in sdist
    assert '"skills" = "birkin/_bundled_skills"' in wheel_files
