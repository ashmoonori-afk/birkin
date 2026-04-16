"""Birkin semantic memory — local embeddings and vector search."""

from birkin.memory.embeddings.encoder import Encoder, SimpleHashEncoder
from birkin.memory.embeddings.store import NumpyVectorStore, VectorStore

__all__ = [
    "Encoder",
    "NumpyVectorStore",
    "SimpleHashEncoder",
    "VectorStore",
]
