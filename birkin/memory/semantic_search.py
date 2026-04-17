"""Semantic search over Wiki Memory using local embeddings."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from birkin.memory.embeddings.encoder import Encoder, SimpleHashEncoder
from birkin.memory.embeddings.store import NumpyVectorStore, SearchResult
from birkin.memory.wiki import WikiMemory

logger = logging.getLogger(__name__)


class SemanticSearch:
    """Semantic search over wiki pages using local embeddings.

    Auto-embeds pages on initialization and provides search methods.
    Falls back to keyword search if encoder is hash-based.

    Usage::

        search = SemanticSearch(wiki, encoder)
        search.index_all()
        results = search.search("async programming in Python", k=5)
    """

    def __init__(
        self,
        memory: WikiMemory,
        encoder: Optional[Encoder] = None,
        persist_path: Optional[Path] = None,
    ) -> None:
        self._memory = memory
        self._encoder = encoder or SimpleHashEncoder()
        self._store = NumpyVectorStore(persist_path=persist_path)

    @property
    def encoder(self) -> Encoder:
        return self._encoder

    @property
    def indexed_count(self) -> int:
        return self._store.count()

    def index_all(self) -> int:
        """Index all wiki pages. Skips re-indexing if page count unchanged."""
        pages = self._memory.list_pages()
        current_count = len(pages)

        if current_count == self._store.count() and self._store.count() > 0:
            return self._store.count()  # skip — already indexed

        count = 0
        for page in pages:
            content = self._memory.get_page(page["category"], page["slug"])
            if content:
                self.index_page(page["category"], page["slug"], content)
                count += 1
        self._store.flush()
        logger.info("Indexed %d wiki pages", count)
        return count

    def index_page(self, category: str, slug: str, content: str) -> None:
        """Index or re-index a single wiki page."""
        page_id = f"{category}/{slug}"
        vector = self._encoder.encode_one(content)
        self._store.upsert(
            page_id,
            vector,
            metadata={"category": category, "slug": slug, "preview": content[:200]},
        )

    def remove_page(self, category: str, slug: str) -> bool:
        """Remove a page from the index."""
        return self._store.delete(f"{category}/{slug}")

    def search(self, query: str, k: int = 10) -> list[SearchResult]:
        """Search for wiki pages semantically similar to the query."""
        if self._store.count() == 0:
            return []
        query_vec = self._encoder.encode_one(query)
        return self._store.search(query_vec, k=k)

    def find_related(self, category: str, slug: str, k: int = 5) -> list[SearchResult]:
        """Find pages related to a given page."""
        content = self._memory.get_page(category, slug)
        if not content:
            return []
        query_vec = self._encoder.encode_one(content)
        results = self._store.search(query_vec, k=k + 1)
        # Exclude the source page itself
        page_id = f"{category}/{slug}"
        return [r for r in results if r.id != page_id][:k]
