"""Tests for birkin.core.defaults module."""

from birkin.core.defaults import DEFAULT_SYSTEM_PROMPT, KARPATHY_GUIDELINES


class TestKarpathyGuidelines:
    def test_contains_four_principles(self):
        assert "Think Before Coding" in KARPATHY_GUIDELINES
        assert "Simplicity First" in KARPATHY_GUIDELINES
        assert "Surgical Changes" in KARPATHY_GUIDELINES
        assert "Goal-Driven Execution" in KARPATHY_GUIDELINES

    def test_guidelines_are_non_empty(self):
        assert len(KARPATHY_GUIDELINES) > 100


class TestDefaultSystemPrompt:
    def test_contains_birkin_identity(self):
        assert "Birkin" in DEFAULT_SYSTEM_PROMPT

    def test_includes_karpathy_guidelines(self):
        assert "Think Before Coding" in DEFAULT_SYSTEM_PROMPT
        assert "Simplicity First" in DEFAULT_SYSTEM_PROMPT
        assert "Surgical Changes" in DEFAULT_SYSTEM_PROMPT
        assert "Goal-Driven Execution" in DEFAULT_SYSTEM_PROMPT

    def test_includes_caution_note(self):
        assert "caution over speed" in DEFAULT_SYSTEM_PROMPT
