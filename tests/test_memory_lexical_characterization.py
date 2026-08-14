"""Characterize the default lexical memory contract before opt-in ranking."""

from birkin import config
from birkin.memory import VaultMemory


def test_default_search_keeps_bm25_order_and_compatibility_shape():
    mem = VaultMemory(config.load_config())
    mem.write_note("Exact", "orchid orchid orchid deployment", source="test")
    mem.write_note("Partial", "orchid gardening", source="test")

    hits = mem.search("orchid deployment", limit=2)

    assert [hit["title"] for hit in hits] == ["exact", "partial"]
    assert set(hits[0]) == {"title", "snippet", "zone", "related"}
    assert "orchid orchid orchid deployment" in hits[0]["snippet"]


def test_default_search_keeps_hangul_bigram_recall():
    mem = VaultMemory(config.load_config())
    mem.write_note("회의", "프로젝트 우선순위를 정했습니다", source="test")

    hits = mem.search("우선순위")

    assert [hit["title"] for hit in hits] == ["회의"]


def test_default_search_keeps_empty_query_behavior():
    mem = VaultMemory(config.load_config())
    mem.write_note("Anything", "some text", source="test")

    assert mem.search("") == []
