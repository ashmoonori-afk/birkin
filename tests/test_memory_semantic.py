from __future__ import annotations

from datetime import datetime, timezone

from birkin import config
from birkin.memory import VaultMemory


class FakeEmbeddingBackend:
    name = "fake-deterministic"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vocab = ("automobile", "vehicle", "recipe")
        return [[float(text.lower().count(word)) for word in vocab]
                for text in texts]


def test_default_backend_is_lexical_only_and_surfaces_signal_contract():
    mem = VaultMemory(config.load_config())
    mem.write_note("Car", "automobile maintenance", source="test")

    hit = mem.search("automobile")[0]

    assert hit["signal_scores"]["lexical"] > 0
    assert hit["signal_scores"]["vector"] == 0
    assert hit["signal_scores"]["entity"] == 0
    assert hit["backend"] == {"lexical": "mnemosyne-bm25"}
    assert hit["source"] == ["lexical"]


def test_vector_backend_is_opt_in_and_can_be_injected_without_optional_extra():
    cfg = {**config.load_config(), "memory_vector_enabled": True}
    mem = VaultMemory(cfg, embedding_backend=FakeEmbeddingBackend())
    mem.write_note("Vehicle guide", "automobile vehicle", source="test")
    mem.write_note("Dinner", "recipe", source="test")

    hit = mem.search("automobile", limit=1)[0]

    assert hit["title"] == "vehicle-guide"
    assert hit["signal_scores"]["vector"] > 0
    assert hit["backend"]["vector"] == "fake-deterministic"
    assert "vector" in hit["source"]


def test_entity_graph_is_opt_in_and_traverses_wikilinks():
    cfg = {**config.load_config(), "memory_entity_enabled": True}
    mem = VaultMemory(cfg)
    mem.write_note("Project Atlas", "migration plan", source="test",
                   links=["Alice"])
    mem.write_note("Alice", "owns the launch checklist", source="test")

    hits = mem.search("Project Atlas", limit=2)
    alice = next(hit for hit in hits if hit["title"] == "alice")

    assert alice["signal_scores"]["entity"] > 0
    assert alice["backend"]["entity"] == "wikilink-entity-graph"
    assert "entity" in alice["source"]


def test_temporal_supersession_ranks_current_fact_first_and_supports_as_of():
    cfg = {**config.load_config(), "memory_temporal_enabled": True}
    mem = VaultMemory(cfg)
    mem.write_note("Old office", "office is Harbor Road", source="test",
                   valid_at="2024-01-01")
    mem.write_note("Current office", "office is Summit Avenue", source="test",
                   valid_at="2025-01-01", supersedes=["Old office"])

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    current = mem.search("office", now=now)
    historical = mem.search("office", as_of="2024-06-01", now=now)

    assert current[0]["title"] == "current-office"
    assert current[0]["signal_scores"]["time"] > current[1]["signal_scores"]["time"]
    assert [hit["title"] for hit in historical] == ["old-office"]


def test_time_range_filter_excludes_non_overlapping_validity():
    cfg = {**config.load_config(), "memory_temporal_enabled": True}
    mem = VaultMemory(cfg)
    mem.write_note("Past", "status report", source="test",
                   valid_at="2023-01-01", invalid_at="2024-01-01")
    mem.write_note("Present", "status report", source="test",
                   valid_at="2025-01-01")

    hits = mem.search("status", since="2025-01-01", until="2025-12-31")

    assert [hit["title"] for hit in hits] == ["present"]


def test_expired_at_is_distinct_from_fact_validity():
    cfg = {**config.load_config(), "memory_temporal_enabled": True}
    mem = VaultMemory(cfg)
    mem.write_note("Correction", "launch code was amber", source="test",
                   valid_at="2024-01-01", expired_at="2025-03-01")

    before = mem.search("amber", as_of="2025-02-01")
    after = mem.search("amber", as_of="2025-04-01")

    assert [hit["title"] for hit in before] == ["correction"]
    assert after == []


def test_tool_renders_per_signal_scores_and_backend():
    mem = VaultMemory(config.load_config())
    mem.write_note("Visible", "contract marker", source="test")
    tool = next(tool for tool in mem.tools() if tool.name == "memory_search")

    result = tool.fn({"query": "marker"}, None)

    assert "lexical=" in result.content
    assert "backend=lexical:mnemosyne-bm25" in result.content
