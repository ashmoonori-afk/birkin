"""A CLI turn must not lose the skill catalog just because routing missed."""

from __future__ import annotations

from pathlib import Path

import pytest

from birkin import config
from birkin.skills import build_manager, validate


@pytest.fixture
def mgr():
    return build_manager(config.load_config())


# -- the gap dogfooding found ---------------------------------------------

def test_english_requests_route(mgr):
    for query in ("review this code", "write tests", "summarize this document"):
        assert mgr.route(query, limit=3), query


def test_korean_requests_mostly_miss_the_keyword_router(mgr):
    """Documents WHY the fallback exists rather than asserting it is fixed.

    Routing is keyword overlap against skill text, which is written in English,
    so a Korean request matches only skills that happen to carry Korean
    trigger words. That is the mechanism working as designed — the fallback
    below is what stops it costing the user their whole catalog.
    """
    misses = [q for q in ("이 코드 리뷰해줘", "테스트 짜줘", "블로그 글 써줘")
              if not mgr.route(q, limit=3)]
    assert misses, "if this ever passes, the catalog gained Korean triggers"


def test_curation_routes_in_korean_now(mgr):
    for query in ("메모리 정리", "벌트 정리해줘"):
        assert "memory-curation" in [s.name for s in mgr.route(query, limit=3)], query


# -- the fallback ----------------------------------------------------------

class _Session:
    """Just enough Session to exercise _build_cli_system."""

    def __init__(self, skills):
        from birkin.agent import Agent
        from birkin.runtime import Session
        from birkin.tools import ToolContext

        class _Mem:
            def render(self):
                return ""

        class _Client:
            provider = "claude-cli"
            model = "m"

        class _Reg:
            def specs(self):
                return []

            def execute(self, *a):
                raise AssertionError

        cfg = {**config.load_config(), "provider": "claude-cli"}
        self.session = Session(
            cfg=cfg, client=_Client(), skills=skills, memory=_Mem(),
            ctx=ToolContext(cfg=cfg, client=_Client(), cwd=Path(".")),
            agent=Agent(client=_Client(), system="", registry=_Reg()))


def test_unrouted_request_still_gets_the_catalog(mgr):
    s = _Session(mgr).session
    s._build_cli_system("이 코드 리뷰해줘")          # routes to nothing
    assert "birkin skills available" in s.agent.system
    assert "neurosis" in s.agent.system, "the index must name real skills"


def test_routed_request_does_not_pay_for_the_index(mgr):
    s = _Session(mgr).session
    s._build_cli_system("review this code")        # routes fine
    assert "birkin skills available" not in s.agent.system


def test_every_cli_turn_carries_skills_one_way_or_the_other(mgr):
    s = _Session(mgr).session
    for query in ("이 코드 리뷰해줘", "review this code", "회의록 정리해줘",
                  "번역해줘", "write tests"):
        s._build_cli_system(query)
        has_index = "birkin skills available" in s.agent.system
        has_routed = "Birkin routed skill" in s.agent.system or \
            "## Skill:" in s.agent.system or len(s.agent.system) > 2000
        assert has_index or has_routed, query


# -- the gate that let it ship --------------------------------------------

def test_when_to_use_is_an_error_for_bundled_skills(tmp_path):
    d = tmp_path / "demo"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n\nbody\n",
                                encoding="utf-8")
    bundled = validate.validate_skill(d / "SKILL.md", source="bundled")
    assert any("When to Use" in e for e in bundled.errors)

    # The user's own skills get advice, not a failed exit code.
    user = validate.validate_skill(d / "SKILL.md", source="user")
    assert not user.errors
    assert any("When to Use" in w for w in user.warnings)


def test_the_bundled_catalog_passes_its_own_gate():
    summary = validate.validate_all()
    bad = [r.name for r in summary.reports
           if r.source == "bundled" and r.errors]
    assert not bad, f"bundled skills failing validation: {bad}"
