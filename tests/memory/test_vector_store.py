"""Tests for vector stores (Numpy + FAISS factory)."""

from __future__ import annotations

from birkin.memory.embeddings.store import NumpyVectorStore, create_vector_store


class TestNumpyVectorStore:
    def test_upsert_and_search(self, tmp_path):
        store = NumpyVectorStore()
        store.upsert("a", [1.0, 0.0, 0.0], {"label": "x"})
        store.upsert("b", [0.0, 1.0, 0.0], {"label": "y"})
        results = store.search([1.0, 0.0, 0.0], k=1)
        assert len(results) == 1
        assert results[0].id == "a"

    def test_delete(self):
        store = NumpyVectorStore()
        store.upsert("a", [1.0, 0.0])
        assert store.delete("a")
        assert store.count() == 0

    def test_persist_roundtrip(self, tmp_path):
        path = tmp_path / "vec.json"
        store = NumpyVectorStore(persist_path=path)
        store.upsert("a", [1.0, 0.0], {"k": "v"})
        store.flush()

        store2 = NumpyVectorStore(persist_path=path)
        assert store2.count() == 1
        results = store2.search([1.0, 0.0], k=1)
        assert results[0].id == "a"


class TestCreateFactory:
    def test_returns_store(self):
        store = create_vector_store()
        assert store is not None
        assert hasattr(store, "upsert")
        assert hasattr(store, "search")

    def test_factory_works_for_operations(self):
        store = create_vector_store()
        store.upsert("x", [0.5, 0.5, 0.0])
        assert store.count() == 1
        results = store.search([0.5, 0.5, 0.0], k=1)
        assert results[0].id == "x"
