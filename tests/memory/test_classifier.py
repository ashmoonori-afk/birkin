"""Tests for the LLM-based memory classifier."""

from __future__ import annotations

import json

# Import core first to avoid circular import:
# memory.__init__ → wiki → core.defaults → core.__init__ → agent → memory.wiki
import birkin.core  # noqa: F401
from birkin.memory.classifier import MemoryClassifier
from tests.fakes import FakeProvider


class TestMemoryClassifier:
    """Tests for MemoryClassifier.classify()."""

    def test_valid_classification_returns_correct_dict(self) -> None:
        """When the provider returns valid JSON, classify returns the parsed dict."""
        expected = {
            "should_save": True,
            "category": "concepts",
            "slug": "transformer-architecture",
            "title": "트랜스포머 아키텍처",
            "tags": ["deep-learning", "transformer"],
        }
        provider = FakeProvider(reply=json.dumps(expected))
        classifier = MemoryClassifier(provider)

        result = classifier.classify(
            "딥러닝에서 트랜스포머 아키텍처를 설명해줘",
            "트랜스포머는 셀프 어텐션 메커니즘을 기반으로 합니다...",
        )

        assert result is not None
        assert result["should_save"] is True
        assert result["category"] == "concepts"
        assert result["slug"] == "transformer-architecture"
        assert result["title"] == "트랜스포머 아키텍처"
        assert result["tags"] == ["deep-learning", "transformer"]

    def test_should_save_false_returns_dict_with_false(self) -> None:
        """When the LLM says should_save=false, classify returns it faithfully."""
        payload = {
            "should_save": False,
            "category": "sessions",
            "slug": "",
            "title": "",
            "tags": [],
        }
        provider = FakeProvider(reply=json.dumps(payload))
        classifier = MemoryClassifier(provider)

        result = classifier.classify("안녕", "안녕하세요!")

        assert result is not None
        assert result["should_save"] is False

    def test_invalid_json_returns_none(self) -> None:
        """When the provider returns invalid JSON, classify returns None."""
        provider = FakeProvider(reply="this is not json {{{")
        classifier = MemoryClassifier(provider)

        result = classifier.classify("some input", "some response")

        assert result is None

    def test_provider_exception_returns_none(self) -> None:
        """When the provider raises an exception, classify returns None."""

        class ExplodingProvider(FakeProvider):
            def complete(self, messages, **kwargs):
                raise RuntimeError("provider exploded")

        classifier = MemoryClassifier(ExplodingProvider())

        result = classifier.classify("some input", "some response")

        assert result is None

    def test_missing_keys_returns_none(self) -> None:
        """When the provider returns JSON missing required keys, returns None."""
        incomplete = {"should_save": True, "category": "concepts"}
        provider = FakeProvider(reply=json.dumps(incomplete))
        classifier = MemoryClassifier(provider)

        result = classifier.classify("some input", "some response")

        assert result is None

    def test_invalid_category_returns_none(self) -> None:
        """When the provider returns an invalid category, returns None."""
        payload = {
            "should_save": True,
            "category": "invalid_category",
            "slug": "test",
            "title": "test",
            "tags": [],
        }
        provider = FakeProvider(reply=json.dumps(payload))
        classifier = MemoryClassifier(provider)

        result = classifier.classify("some input", "some response")

        assert result is None

    def test_entities_category_accepted(self) -> None:
        """Entities is a valid category."""
        payload = {
            "should_save": True,
            "category": "entities",
            "slug": "jensen-huang",
            "title": "Jensen Huang",
            "tags": ["nvidia"],
        }
        provider = FakeProvider(reply=json.dumps(payload))
        classifier = MemoryClassifier(provider)

        result = classifier.classify("Who is Jensen Huang?", "He is the CEO of NVIDIA...")

        assert result is not None
        assert result["category"] == "entities"
