from __future__ import annotations

from birkin import config
from birkin.memory import VaultMemory
from birkin.mnemosyne import ARCHIVE_ZONE


class MatchingEmbeddingBackend:
    name = "matching-test-backend"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] for _text in texts]


def _semantic_memory() -> VaultMemory:
    cfg = {
        **config.load_config(),
        "memory_vector_enabled": True,
        "memory_entity_enabled": True,
    }
    return VaultMemory(cfg, embedding_backend=MatchingEmbeddingBackend())


def test_search_hides_archived_note_when_vector_and_entity_are_enabled() -> None:
    # Given a note that has been moved into the archive zone.
    memory = _semantic_memory()
    memory.write_note("Archived launch marker", "historical plan", source="test")
    memory.rezone("Archived launch marker", ARCHIVE_ZONE)

    # When semantic search uses both optional candidate sources.
    results = memory.search("Archived launch marker")

    # Then the archived note remains hidden from public search.
    assert results == []


def test_search_hides_expired_note_when_vector_and_entity_are_enabled() -> None:
    # Given a note whose explicit expiry date is in the past.
    memory = _semantic_memory()
    memory.write_note(
        "Expired launch marker",
        "obsolete plan",
        source="test",
        expired_at="2000-01-01",
    )

    # When semantic search uses both optional candidate sources.
    results = memory.search("Expired launch marker")

    # Then the expired note remains hidden from public search.
    assert results == []
