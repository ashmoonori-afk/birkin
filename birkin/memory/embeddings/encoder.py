"""Embedding encoder — abstract interface and implementations.

Supports optional heavy dependencies (sentence-transformers) with
a lightweight hash-based fallback for environments without GPU/models.
"""

from __future__ import annotations

import hashlib
import logging
import math
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# Type alias — vectors are plain list[float] to avoid numpy dependency at import
Vector = list[float]

_DEFAULT_DIM = 384  # BGE-small / MiniLM dimension


class Encoder(ABC):
    """Abstract encoder that converts text to dense vectors."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Embedding dimensionality."""
        ...

    @abstractmethod
    def encode(self, texts: list[str]) -> list[Vector]:
        """Encode a batch of texts into vectors."""
        ...

    def encode_one(self, text: str) -> Vector:
        """Convenience: encode a single text."""
        return self.encode([text])[0]


class SimpleHashEncoder(Encoder):
    """Deterministic hash-based encoder for testing and fallback.

    Produces pseudo-random but deterministic vectors from text using
    SHA-256. Not semantically meaningful, but allows the pipeline to
    function without ML dependencies.
    """

    def __init__(self, dimension: int = _DEFAULT_DIM) -> None:
        self._dim = dimension

    @property
    def dimension(self) -> int:
        return self._dim

    def encode(self, texts: list[str]) -> list[Vector]:
        return [self._hash_to_vector(t) for t in texts]

    def _hash_to_vector(self, text: str) -> Vector:
        """Generate a deterministic unit vector from text via SHA-256 expansion."""
        raw: list[float] = []
        i = 0
        while len(raw) < self._dim:
            h = hashlib.sha256(f"{text}:{i}".encode()).digest()
            # Convert each byte to [-1, 1] range
            raw.extend((b / 127.5) - 1.0 for b in h)
            i += 1
        raw = raw[: self._dim]
        # L2 normalize
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]


class SentenceTransformerEncoder(Encoder):
    """Encoder using sentence-transformers (optional dependency).

    Supports BGE-m3 (bilingual KO+EN) and any HuggingFace model.
    Falls back to SimpleHashEncoder if sentence-transformers is not installed.
    """

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        self._model_name = model_name
        self._model = None
        self._dim = _DEFAULT_DIM
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(model_name)
            self._dim = self._model.get_sentence_embedding_dimension()
            logger.info("Loaded sentence-transformers model: %s (dim=%d)", model_name, self._dim)
        except ImportError:
            logger.warning("sentence-transformers not installed. Using hash fallback.")
        except (OSError, RuntimeError) as exc:
            logger.warning("Failed to load model %s: %s. Using hash fallback.", model_name, exc)

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def available(self) -> bool:
        return self._model is not None

    def encode(self, texts: list[str]) -> list[Vector]:
        if self._model is None:
            return SimpleHashEncoder(self._dim).encode(texts)
        embeddings = self._model.encode(texts, normalize_embeddings=True)
        return [e.tolist() for e in embeddings]
