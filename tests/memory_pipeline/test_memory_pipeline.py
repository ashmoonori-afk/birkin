"""Tests for memory pipeline — event store, compiler, semantic search."""

from __future__ import annotations

from pathlib import Path

from birkin.memory.compiler import MemoryCompiler
from birkin.memory.embeddings.encoder import SimpleHashEncoder
from birkin.memory.embeddings.store import NumpyVectorStore, _cosine_similarity
from birkin.memory.event_store import EventStore
from birkin.memory.events import RawEvent, TokenUsageRecord
from birkin.memory.semantic_search import SemanticSearch
from birkin.memory.wiki import WikiMemory

# ---------------------------------------------------------------------------
# Event Store
# ---------------------------------------------------------------------------


class TestEventStore:
    def test_append_and_count(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "events.db")
        store.append(RawEvent(session_id="s1", event_type="user_message"))
        store.append(RawEvent(session_id="s1", event_type="llm_call"))
        assert store.count() == 2
        assert store.count("s1") == 2
        assert store.count("s2") == 0
        store.close()

    def test_query_by_session(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "events.db")
        store.append(RawEvent(session_id="s1", event_type="user_message"))
        store.append(RawEvent(session_id="s2", event_type="llm_call"))
        events = store.query(session_id="s1")
        assert len(events) == 1
        assert events[0].session_id == "s1"
        store.close()

    def test_query_by_type(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "events.db")
        store.append(RawEvent(session_id="s1", event_type="user_message"))
        store.append(RawEvent(session_id="s1", event_type="tool_call"))
        events = store.query(event_type="tool_call")
        assert len(events) == 1
        store.close()

    def test_tokens_roundtrip(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "events.db")
        store.append(
            RawEvent(
                session_id="s1",
                event_type="llm_call",
                tokens=TokenUsageRecord(tokens_in=100, tokens_out=200, cost_usd=0.05),
            )
        )
        events = store.query(session_id="s1")
        assert events[0].tokens.tokens_in == 100
        assert events[0].tokens.tokens_out == 200
        assert events[0].tokens.cost_usd == 0.05
        store.close()

    def test_since(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "events.db")
        store.append(RawEvent(session_id="s1", timestamp="2026-04-16T10:00:00Z"))
        store.append(RawEvent(session_id="s1", timestamp="2026-04-16T12:00:00Z"))
        events = store.since("2026-04-16T11:00:00Z")
        assert len(events) == 1
        store.close()


# ---------------------------------------------------------------------------
# Memory Compiler
# ---------------------------------------------------------------------------


class TestMemoryCompiler:
    def test_compile_session(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "events.db")
        mem = WikiMemory(root=tmp_path / "memory")
        mem.init()

        store.append(RawEvent(session_id="s1", event_type="user_message", payload={"content": "Hello world"}))
        store.append(
            RawEvent(
                session_id="s1",
                event_type="llm_call",
                provider="anthropic",
                tokens=TokenUsageRecord(tokens_in=50, tokens_out=100),
            )
        )

        compiler = MemoryCompiler(store, mem)
        result = compiler.compile_session("s1")
        assert result.events_processed == 2
        assert len(result.pages_created) == 1

        page = mem.get_page("sessions", result.pages_created[0])
        assert page is not None
        assert "anthropic" in page
        store.close()

    def test_compile_empty_session(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "events.db")
        mem = WikiMemory(root=tmp_path / "memory")
        mem.init()

        compiler = MemoryCompiler(store, mem)
        result = compiler.compile_session("nonexistent")
        assert result.events_processed == 0
        store.close()

    def test_extract_entities(self, tmp_path: Path) -> None:
        store = EventStore(tmp_path / "events.db")
        mem = WikiMemory(root=tmp_path / "memory")
        mem.init()

        events = [
            RawEvent(
                event_type="user_message",
                payload={"content": "Tell me about Google Cloud Platform and its services"},
            ),
        ]
        compiler = MemoryCompiler(store, mem)
        entities = compiler.extract_entities(events)
        names = [e["name"] for e in entities]
        assert any("Google" in n for n in names)
        store.close()


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


class TestSimpleHashEncoder:
    def test_deterministic(self) -> None:
        enc = SimpleHashEncoder(dimension=64)
        v1 = enc.encode_one("hello")
        v2 = enc.encode_one("hello")
        assert v1 == v2

    def test_dimension(self) -> None:
        enc = SimpleHashEncoder(dimension=128)
        v = enc.encode_one("test")
        assert len(v) == 128

    def test_normalized(self) -> None:
        import math

        enc = SimpleHashEncoder(dimension=64)
        v = enc.encode_one("test")
        norm = math.sqrt(sum(x * x for x in v))
        assert abs(norm - 1.0) < 1e-6

    def test_batch_encode(self) -> None:
        enc = SimpleHashEncoder()
        vecs = enc.encode(["a", "b", "c"])
        assert len(vecs) == 3


class TestNumpyVectorStore:
    def test_upsert_and_search(self) -> None:
        store = NumpyVectorStore()
        enc = SimpleHashEncoder(dimension=32)

        store.upsert("a", enc.encode_one("python programming"), {"title": "Python"})
        store.upsert("b", enc.encode_one("rust ownership"), {"title": "Rust"})
        store.upsert("c", enc.encode_one("javascript web"), {"title": "JS"})

        results = store.search(enc.encode_one("python programming"), k=2)
        assert len(results) == 2
        assert results[0].id == "a"  # exact match should be first
        assert results[0].score > 0.9

    def test_delete(self) -> None:
        store = NumpyVectorStore()
        store.upsert("a", [1.0, 0.0], {})
        assert store.count() == 1
        store.delete("a")
        assert store.count() == 0

    def test_persistence(self, tmp_path: Path) -> None:
        path = tmp_path / "vectors.json"
        store = NumpyVectorStore(persist_path=path)
        store.upsert("a", [1.0, 0.0], {"x": 1})
        assert path.is_file()

        store2 = NumpyVectorStore(persist_path=path)
        assert store2.count() == 1

    def test_cosine_similarity(self) -> None:
        assert abs(_cosine_similarity([1, 0], [1, 0]) - 1.0) < 1e-6
        assert abs(_cosine_similarity([1, 0], [0, 1])) < 1e-6
        assert abs(_cosine_similarity([1, 0], [-1, 0]) + 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Semantic Search
# ---------------------------------------------------------------------------


class TestSemanticSearch:
    def test_index_and_search(self, tmp_path: Path) -> None:
        mem = WikiMemory(root=tmp_path / "memory")
        mem.init()
        mem.ingest("concepts", "py-async", "# Python Async\nAsyncio patterns.")
        mem.ingest("concepts", "rust-own", "# Rust Ownership\nBorrow checker.")
        mem.ingest("entities", "birkin", "# Birkin\nAI agent platform.")

        search = SemanticSearch(mem, SimpleHashEncoder())
        count = search.index_all()
        assert count == 3
        assert search.indexed_count == 3

        results = search.search("Python concurrency", k=3)
        assert len(results) == 3

    def test_find_related(self, tmp_path: Path) -> None:
        mem = WikiMemory(root=tmp_path / "memory")
        mem.init()
        mem.ingest("concepts", "a", "Topic A content")
        mem.ingest("concepts", "b", "Topic B content")

        search = SemanticSearch(mem, SimpleHashEncoder())
        search.index_all()

        related = search.find_related("concepts", "a", k=1)
        assert len(related) == 1
        assert related[0].id != "concepts/a"

    def test_remove_page(self, tmp_path: Path) -> None:
        mem = WikiMemory(root=tmp_path / "memory")
        mem.init()
        mem.ingest("concepts", "x", "Content X")

        search = SemanticSearch(mem, SimpleHashEncoder())
        search.index_all()
        assert search.indexed_count == 1

        search.remove_page("concepts", "x")
        assert search.indexed_count == 0

    def test_empty_search(self, tmp_path: Path) -> None:
        mem = WikiMemory(root=tmp_path / "memory")
        mem.init()
        search = SemanticSearch(mem, SimpleHashEncoder())
        results = search.search("anything")
        assert results == []
