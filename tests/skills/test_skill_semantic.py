"""Tests for hybrid (exact + semantic) skill trigger matching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from birkin.skills.registry import SkillRegistry
from birkin.skills.schema import Skill, SkillSpec

# -- helpers ----------------------------------------------------------------


def _make_skill(name: str, triggers: list[str], description: str = "") -> Skill:
    return Skill(
        spec=SkillSpec(
            name=name,
            description=description or f"Skill {name}",
            triggers=triggers,
        ),
        instructions="",
        path=Path("/tmp/fake"),
        enabled=True,
    )


def _registry_with_skills(skills: list[Skill], semantic=None) -> SkillRegistry:
    reg = SkillRegistry(skills_dir=None, semantic_search=semantic)
    for s in skills:
        reg._skills[s.name] = s
        reg._tools[s.name] = []
    return reg


# -- tests ------------------------------------------------------------------


class TestExactMatchPreserved:
    def test_exact_substring_match_no_semantic(self):
        """Without SemanticSearch, exact substring still works."""
        skills = [
            _make_skill("email", ["send email", "mail"]),
            _make_skill("search", ["web search", "google"]),
        ]
        reg = _registry_with_skills(skills)
        matches = reg.match_triggers("I want to send email")
        assert len(matches) == 1
        assert matches[0].name == "email"

    def test_no_match_returns_empty(self):
        skills = [_make_skill("email", ["send email"])]
        reg = _registry_with_skills(skills)
        matches = reg.match_triggers("unrelated text about cooking")
        assert matches == []


class TestSemanticFallback:
    def test_semantic_fallback_finds_match(self):
        """When exact match fails, semantic search kicks in."""
        skills = [
            _make_skill("email", ["send email", "mail"], "Send emails to contacts"),
        ]

        mock_result = MagicMock()
        mock_result.score = 0.85
        mock_result.metadata = {"slug": "email"}

        mock_semantic = MagicMock()
        mock_semantic.search.return_value = [mock_result]

        reg = _registry_with_skills(skills, semantic=mock_semantic)
        # "거래처에 견적서 전달해" has no substring match with "send email"
        matches = reg.match_triggers("거래처에 견적서 전달해")
        assert len(matches) == 1
        assert matches[0].name == "email"
        mock_semantic.search.assert_called_once()

    def test_semantic_below_threshold_ignored(self):
        """Low-confidence semantic results are filtered out."""
        skills = [
            _make_skill("email", ["send email"], "Send emails"),
        ]

        mock_result = MagicMock()
        mock_result.score = 0.3  # below 0.6 threshold
        mock_result.metadata = {"slug": "email"}

        mock_semantic = MagicMock()
        mock_semantic.search.return_value = [mock_result]

        reg = _registry_with_skills(skills, semantic=mock_semantic)
        matches = reg.match_triggers("completely unrelated gibberish")
        assert matches == []

    def test_semantic_not_called_when_exact_matches(self):
        """Semantic search is skipped when exact match succeeds."""
        skills = [_make_skill("email", ["send email"])]

        mock_semantic = MagicMock()
        reg = _registry_with_skills(skills, semantic=mock_semantic)
        matches = reg.match_triggers("send email to John")
        assert len(matches) == 1
        mock_semantic.search.assert_not_called()
