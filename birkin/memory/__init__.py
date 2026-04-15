"""LLM Wiki memory backend for Birkin agents.

Implements Andrej Karpathy's LLM Wiki pattern: a persistent, LLM-maintained
knowledge base stored as plain markdown files. Knowledge is compiled once and
kept current, not re-derived on every query.

Architecture:
    raw/      — Immutable source material (user docs, API refs, etc.)
    wiki/     — LLM-compiled knowledge pages (entities, concepts, sessions)
    schema.md — Structure rules for the memory

Reference: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
"""

from birkin.memory.wiki import WikiMemory

__all__ = ["WikiMemory"]
