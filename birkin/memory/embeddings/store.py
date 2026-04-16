"""Vector store — in-memory storage with cosine similarity search."""

from __future__ import annotations

import json
import logging
import math
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from birkin.memory.embeddings.encoder import Vector

logger = logging.getLogger(__name__)


class SearchResult:
    """A single search result with score and metadata."""

    __slots__ = ("id", "score", "metadata")

    def __init__(self, id: str, score: float, metadata: dict[str, Any]) -> None:
        self.id = id
        self.score = score
        self.metadata = metadata

    def __repr__(self) -> str:
        return f"SearchResult({self.id!r}, score={self.score:.4f})"


class VectorStore(ABC):
    """Abstract vector store interface."""

    @abstractmethod
    def upsert(self, id: str, vector: Vector, metadata: Optional[dict[str, Any]] = None) -> None:
        ...

    @abstractmethod
    def search(self, query_vec: Vector, k: int = 10) -> list[SearchResult]:
        ...

    @abstractmethod
    def delete(self, id: str) -> bool:
        ...

    @abstractmethod
    def count(self) -> int:
        ...


def _cosine_similarity(a: Vector, b: Vector) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class NumpyVectorStore(VectorStore):
    """In-memory vector store with pure-Python cosine similarity.

    No numpy dependency despite the name — uses pure Python math.
    Suitable for small-to-medium datasets (< 100k vectors).
    Supports persistence to a JSON file.

    Usage::

        store = NumpyVectorStore()
        store.upsert("page1", [0.1, 0.2, ...], {"title": "Python"})
        results = store.search(query_vec, k=5)
    """

    def __init__(self, persist_path: Optional[Path] = None) -> None:
        self._vectors: dict[str, Vector] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._persist_path = persist_path
        if persist_path and persist_path.is_file():
            self._load()

    def upsert(self, id: str, vector: Vector, metadata: Optional[dict[str, Any]] = None) -> None:
        self._vectors[id] = vector
        self._metadata[id] = metadata or {}
        if self._persist_path:
            self._save()

    def search(self, query_vec: Vector, k: int = 10) -> list[SearchResult]:
        if not self._vectors:
            return []

        scored: list[tuple[float, str]] = []
        for id, vec in self._vectors.items():
            score = _cosine_similarity(query_vec, vec)
            scored.append((score, id))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            SearchResult(id=id, score=score, metadata=self._metadata.get(id, {}))
            for score, id in scored[:k]
        ]

    def delete(self, id: str) -> bool:
        if id in self._vectors:
            del self._vectors[id]
            self._metadata.pop(id, None)
            if self._persist_path:
                self._save()
            return True
        return False

    def count(self) -> int:
        return len(self._vectors)

    def _save(self) -> None:
        if not self._persist_path:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "vectors": self._vectors,
            "metadata": self._metadata,
        }
        self._persist_path.write_text(json.dumps(data, default=str), encoding="utf-8")

    def _load(self) -> None:
        if not self._persist_path or not self._persist_path.is_file():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            self._vectors = data.get("vectors", {})
            self._metadata = data.get("metadata", {})
            logger.info("Loaded %d vectors from %s", len(self._vectors), self._persist_path)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load vector store: %s", exc)
