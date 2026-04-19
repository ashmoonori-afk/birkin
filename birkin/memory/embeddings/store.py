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
    def upsert(self, id: str, vector: Vector, metadata: Optional[dict[str, Any]] = None) -> None: ...

    @abstractmethod
    def search(self, query_vec: Vector, k: int = 10) -> list[SearchResult]: ...

    @abstractmethod
    def delete(self, id: str) -> bool: ...

    @abstractmethod
    def count(self) -> int: ...


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
        self._dirty = False
        if persist_path and persist_path.is_file():
            self._load()

    def upsert(self, id: str, vector: Vector, metadata: Optional[dict[str, Any]] = None) -> None:
        self._vectors[id] = vector
        self._metadata[id] = metadata or {}
        self._dirty = True

    def flush(self) -> None:
        """Persist pending changes to disk."""
        if self._dirty and self._persist_path:
            self._save()
            self._dirty = False

    def search(self, query_vec: Vector, k: int = 10) -> list[SearchResult]:
        if not self._vectors:
            return []

        scored: list[tuple[float, str]] = []
        for id, vec in self._vectors.items():
            score = _cosine_similarity(query_vec, vec)
            scored.append((score, id))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [SearchResult(id=id, score=score, metadata=self._metadata.get(id, {})) for score, id in scored[:k]]

    def delete(self, id: str) -> bool:
        if id in self._vectors:
            del self._vectors[id]
            self._metadata.pop(id, None)
            self._dirty = True
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


class FAISSVectorStore(VectorStore):
    """FAISS-backed vector store for 10k+ items.

    Requires ``faiss-cpu``. Use :func:`create_vector_store` factory
    which falls back to :class:`NumpyVectorStore` automatically.
    """

    def __init__(self, persist_path: Optional[Path] = None, dimension: int = 384) -> None:
        try:
            import faiss  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError("faiss-cpu required: pip install faiss-cpu") from exc

        self._faiss = faiss
        self._dimension = dimension
        self._persist_path = persist_path
        self._index = faiss.IndexFlatIP(dimension)
        self._id_map: list[str] = []
        self._metadata: dict[str, dict[str, Any]] = {}
        if persist_path:
            self._load()

    def upsert(self, id: str, vector: Vector, metadata: Optional[dict[str, Any]] = None) -> None:
        import numpy as np

        # Remove old entry if updating
        if id in self._id_map:
            self.delete(id)

        vec = np.array([vector], dtype=np.float32)
        self._faiss.normalize_L2(vec)
        self._index.add(vec)
        self._id_map.append(id)
        if metadata:
            self._metadata[id] = metadata

    def search(self, query_vec: Vector, k: int = 10) -> list[SearchResult]:
        import numpy as np

        if self._index.ntotal == 0:
            return []
        vec = np.array([query_vec], dtype=np.float32)
        self._faiss.normalize_L2(vec)
        scores, indices = self._index.search(vec, min(k, self._index.ntotal))
        results: list[SearchResult] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._id_map):
                continue
            results.append(
                SearchResult(
                    id=self._id_map[idx],
                    score=float(score),
                    metadata=self._metadata.get(self._id_map[idx], {}),
                )
            )
        return results

    def delete(self, id: str) -> bool:
        if id not in self._id_map:
            return False
        # FAISS IndexFlat doesn't support single delete — rebuild
        idx = self._id_map.index(id)
        self._id_map.pop(idx)
        self._metadata.pop(id, None)
        if self._index.ntotal > 0:
            import numpy as np

            all_vecs = self._faiss.rev_swig_ptr(self._index.get_xb(), self._index.ntotal * self._dimension)
            all_vecs = np.array(all_vecs).reshape(-1, self._dimension)
            new_vecs = np.delete(all_vecs, idx, axis=0)
            self._index.reset()
            if len(new_vecs) > 0:
                self._index.add(new_vecs)
        return True

    def count(self) -> int:
        return self._index.ntotal

    def flush(self) -> None:
        if self._persist_path:
            self._save()

    def _save(self) -> None:
        if not self._persist_path:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._faiss.write_index(self._index, str(self._persist_path.with_suffix(".faiss")))
        meta_path = self._persist_path.with_suffix(".meta.json")
        meta_path.write_text(
            json.dumps({"ids": self._id_map, "metadata": self._metadata}, default=str),
            encoding="utf-8",
        )

    def _load(self) -> None:
        if not self._persist_path:
            return
        faiss_path = self._persist_path.with_suffix(".faiss")
        meta_path = self._persist_path.with_suffix(".meta.json")
        if not faiss_path.is_file():
            return
        try:
            self._index = self._faiss.read_index(str(faiss_path))
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            self._id_map = data.get("ids", [])
            self._metadata = data.get("metadata", {})
            logger.info("Loaded FAISS index: %d vectors", self._index.ntotal)
        except (json.JSONDecodeError, OSError, RuntimeError) as exc:
            logger.warning("Failed to load FAISS index: %s", exc)


def create_vector_store(persist_path: Optional[Path] = None, dimension: int = 384) -> VectorStore:
    """Factory: use FAISS if available, fall back to NumpyVectorStore."""
    try:
        return FAISSVectorStore(persist_path=persist_path, dimension=dimension)
    except ImportError:
        return NumpyVectorStore(persist_path=persist_path)
