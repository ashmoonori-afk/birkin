"""Context injector — auto-inject relevant user context before agent calls."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel

from birkin.core.context.profile import UserProfile

if TYPE_CHECKING:
    from birkin.memory.semantic_search import SemanticSearch
    from birkin.memory.wiki import WikiMemory

logger = logging.getLogger(__name__)


class InjectedContext(BaseModel):
    """Result of context injection — what was added to the prompt."""

    system_addition: str = ""
    source_pages: list[str] = []
    tokens_added: int = 0


class ContextInjector:
    """Auto-injects relevant user context into system prompts.

    Pulls relevant wiki pages via semantic search and formats them
    for system prompt injection.

    Usage::

        injector = ContextInjector(wiki, semantic_search)
        ctx = injector.build_context("How does our API auth work?", budget_tokens=2000)
        # ctx.system_addition contains the formatted context to append
    """

    def __init__(
        self,
        memory: "WikiMemory",
        search: "Optional[SemanticSearch]" = None,
        profile: Optional[UserProfile] = None,
    ) -> None:
        self._memory = memory
        self._search = search
        self._profile = profile or UserProfile()

    @property
    def profile(self) -> UserProfile:
        return self._profile

    def build_context(
        self,
        user_message: str,
        *,
        budget_tokens: int = 2000,
        max_pages: int = 5,
        style: str = "xml",
    ) -> InjectedContext:
        """Build context to inject into the system prompt.

        Args:
            user_message: The user's current message (used for relevance search).
            budget_tokens: Max approximate tokens for injected context.
            max_pages: Max number of wiki pages to include.
            style: Format style — 'xml', 'markdown', or 'json'.

        Returns:
            InjectedContext with the formatted addition and metadata.
        """
        pages = self._select_relevant_pages(user_message, max_pages)
        formatted = self._format_for_prompt(pages, style)

        # Rough token estimate (4 chars per token)
        estimated_tokens = len(formatted) // 4
        if estimated_tokens > budget_tokens and pages:
            # Trim pages to fit budget
            while estimated_tokens > budget_tokens and pages:
                pages.pop()
                formatted = self._format_for_prompt(pages, style)
                estimated_tokens = len(formatted) // 4

        # Add profile section
        profile_section = self._profile.to_prompt_section()
        if profile_section:
            formatted = f"{profile_section}\n\n{formatted}"
            estimated_tokens = len(formatted) // 4

        return InjectedContext(
            system_addition=formatted,
            source_pages=[p["id"] for p in pages],
            tokens_added=estimated_tokens,
        )

    def _select_relevant_pages(self, query: str, max_pages: int) -> list[dict]:
        """Select relevant wiki pages for the query."""
        if self._search and self._search.indexed_count > 0:
            results = self._search.search(query, k=max_pages)
            return [
                {
                    "id": r.id,
                    "score": r.score,
                    "content": r.metadata.get("preview", ""),
                }
                for r in results
                if r.score > 0.1
            ]

        # Fallback to keyword search
        keyword_results = self._memory.query(query)
        return [
            {
                "id": f"{r['category']}/{r['slug']}",
                "score": 1.0,
                "content": r.get("snippet", ""),
            }
            for r in keyword_results[:max_pages]
        ]

    @staticmethod
    def _format_for_prompt(pages: list[dict], style: str) -> str:
        """Format selected pages for system prompt injection."""
        if not pages:
            return ""

        if style == "xml":
            parts = ["<user_context>"]
            for page in pages:
                parts.append(f'  <page id="{page["id"]}">')
                parts.append(f"    {page['content']}")
                parts.append("  </page>")
            parts.append("</user_context>")
            return "\n".join(parts)

        if style == "markdown":
            parts = ["## Relevant Context\n"]
            for page in pages:
                parts.append(f"### {page['id']}")
                parts.append(page["content"])
                parts.append("")
            return "\n".join(parts)

        # json style
        import json

        return json.dumps({"context_pages": pages}, indent=2)
