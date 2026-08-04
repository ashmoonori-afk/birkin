"""Checking that a citation actually supports the claim attached to it.

birkin already ships two skills that TELL the model to cite: fact-checking
("verify a claim against 2+ primary sources") and deep-research ("synthesize
sources into a cited report"). Neither can CHECK a citation, and that is the
failure mode worth catching -- a model that has been told to cite will cite.
It will attach a plausible URL to a sentence that URL does not support, and
prose instructing it not to cannot detect when it has.

So this is code, not more prose: given claims and the text actually fetched
from each source, decide per claim whether the source supports it, and refuse
the ones where it does not.

The matching is deliberately lexical -- overlap of content words, plus the
numbers and years that carry most factual weight. It cannot judge meaning, and
it does not pretend to: a claim whose support is real but paraphrased comes
back "unsupported", which costs a re-check. The opposite error, blessing a
citation that says nothing of the kind, is the one that puts a false fact in
front of the user with a footnote on it.
"""

from __future__ import annotations

import pytest

from birkin import grounded

KAGGLE = ("Kaggriculture is a Kaggle competition about agricultural data, "
          "and submissions close on 30 September 2026. The evaluation metric "
          "is root mean squared error and entries are submitted as CSV.")


class TestASupportedClaimPasses:
    def test_a_claim_the_source_states_is_supported(self) -> None:
        result = grounded.check_claim(
            "Kaggriculture submissions close on 30 September 2026.",
            [{"url": "https://kaggle.test/c/kaggriculture", "text": KAGGLE}])
        assert result.supported is True
        assert result.source_url == "https://kaggle.test/c/kaggriculture"

    def test_the_supporting_sentence_is_quoted_back(self) -> None:
        """A verdict without the evidence is just another assertion."""
        result = grounded.check_claim(
            "The evaluation metric is root mean squared error.",
            [{"url": "https://kaggle.test/c", "text": KAGGLE}])
        assert result.supported is True
        assert "root mean squared error" in result.quote

    def test_the_best_source_wins_when_several_are_offered(self) -> None:
        result = grounded.check_claim(
            "Submissions close on 30 September 2026.",
            [{"url": "https://unrelated.test", "text": "A page about bicycles."},
             {"url": "https://kaggle.test/c", "text": KAGGLE}])
        assert result.supported is True
        assert result.source_url == "https://kaggle.test/c"


class TestAnUnsupportedClaimIsRefused:
    def test_a_claim_the_source_never_makes_is_unsupported(self) -> None:
        """The core case: a real URL attached to a sentence it does not support."""
        result = grounded.check_claim(
            "The prize pool is 100,000 dollars.",
            [{"url": "https://kaggle.test/c", "text": KAGGLE}])
        assert result.supported is False

    def test_a_wrong_number_is_not_supported_by_the_right_sentence(self) -> None:
        """Numbers carry the fact. 'closes 30 September' must not support '30 October'."""
        result = grounded.check_claim(
            "Kaggriculture submissions close on 30 October 2026.",
            [{"url": "https://kaggle.test/c", "text": KAGGLE}])
        assert result.supported is False

    def test_a_claim_with_no_sources_at_all_is_unsupported(self) -> None:
        result = grounded.check_claim("Anything at all.", [])
        assert result.supported is False
        assert result.source_url == ""

    def test_an_empty_source_body_supports_nothing(self) -> None:
        result = grounded.check_claim(
            "Submissions close on 30 September 2026.",
            [{"url": "https://kaggle.test/c", "text": ""}])
        assert result.supported is False


class TestKoreanClaims:
    def test_a_supported_korean_claim(self) -> None:
        source = ("이 대회의 평가 지표는 RMSE이며 제출 마감일은 2026년 9월 30일입니다. "
                  "제출 형식은 CSV입니다.")
        result = grounded.check_claim(
            "제출 마감일은 2026년 9월 30일입니다.",
            [{"url": "https://kaggle.test/ko", "text": source}])
        assert result.supported is True

    def test_an_unsupported_korean_claim(self) -> None:
        source = "이 대회의 평가 지표는 RMSE입니다."
        result = grounded.check_claim(
            "상금은 1억 원입니다.",
            [{"url": "https://kaggle.test/ko", "text": source}])
        assert result.supported is False


class TestTheReport:
    CLAIMS = ["Kaggriculture submissions close on 30 September 2026.",
              "The prize pool is 100,000 dollars."]
    SOURCES = [{"url": "https://kaggle.test/c", "text": KAGGLE}]

    def test_it_separates_supported_from_unsupported(self) -> None:
        report = grounded.verify(self.CLAIMS, self.SOURCES)
        assert report.supported_count == 1
        assert len(report.unsupported) == 1
        assert "prize pool" in report.unsupported[0].claim

    def test_the_rendering_names_every_unsupported_claim(self) -> None:
        text = grounded.verify(self.CLAIMS, self.SOURCES).render()
        assert "UNSUPPORTED" in text
        assert "prize pool" in text

    def test_a_fully_supported_report_says_so(self) -> None:
        report = grounded.verify([self.CLAIMS[0]], self.SOURCES)
        assert report.all_supported is True
        assert "UNSUPPORTED" not in report.render()

    def test_no_claims_is_not_a_pass(self) -> None:
        """Nothing to check is not the same as everything checked out."""
        assert grounded.verify([], self.SOURCES).all_supported is False


class TestTheTool:
    def test_the_tool_is_registered_in_the_web_group(self) -> None:
        from pathlib import Path

        from birkin.tools import ToolContext, build_registry
        registry = build_registry(ToolContext(cfg={}, client=None,
                                              cwd=Path(".")))
        assert "verify_citations" in registry.names()

    def test_it_reports_the_unsupported_claim(self, tmp_path) -> None:
        from birkin.tools import ToolContext, build_registry
        registry = build_registry(ToolContext(cfg={"spill_threshold": 0},
                                              client=None, cwd=tmp_path))
        result = registry.execute("verify_citations", {
            "claims": ["The prize pool is 100,000 dollars."],
            "sources": [{"url": "https://kaggle.test/c", "text": KAGGLE}]})
        assert "UNSUPPORTED" in result.content

    def test_malformed_input_is_an_error_not_a_crash(self, tmp_path) -> None:
        from birkin.tools import ToolContext, build_registry
        registry = build_registry(ToolContext(cfg={"spill_threshold": 0},
                                              client=None, cwd=tmp_path))
        result = registry.execute("verify_citations", {"claims": "not a list"})
        assert result.is_error is True


class TestTheSkillShips:
    def test_the_skill_passes_birkins_own_validator(self) -> None:
        """The frontmatter contract, checked by the code that enforces it."""
        from pathlib import Path

        from birkin.skills import validate

        skill_md = (Path(__file__).resolve().parent.parent / "skills"
                    / "research" / "grounded-citations" / "SKILL.md")
        assert skill_md.is_file()
        report = validate.validate_skill(skill_md, source="bundled")
        assert report.errors == []

    def test_it_names_the_tool_it_depends_on(self) -> None:
        """A skill telling the model to use a tool that is not wired is a dead end."""
        from pathlib import Path

        from birkin.tools import ToolContext, build_registry

        skill_md = (Path(__file__).resolve().parent.parent / "skills"
                    / "research" / "grounded-citations" / "SKILL.md")
        body = skill_md.read_text(encoding="utf-8")
        registry = build_registry(ToolContext(cfg={}, client=None,
                                              cwd=Path(".")))
        named = [tool for tool in ("verify_citations", "web_fetch")
                 if tool in body]
        assert named, "the skill names no tool"
        for tool in named:
            assert tool in registry.names()
