"""Wiki read tool — on-demand full page retrieval from memory."""

from __future__ import annotations

from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec


class WikiReadTool(Tool):
    """Read the full content of a wiki memory page on demand.

    The system prompt contains a compact index of pages (title + tags).
    The agent calls this tool when it needs the full content of a specific page.
    This saves tokens by not injecting all pages into every prompt.
    """

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="wiki_read",
            description=(
                "Read the full content of a wiki memory page. "
                "Use slugs from the memory index in the system prompt. "
                "Example: wiki_read(category='concepts', slug='python-asyncio')"
            ),
            parameters=[
                ToolParameter(
                    name="category", type="string", description="Page category (entities, concepts, sessions)"
                ),
                ToolParameter(name="slug", type="string", description="Page slug from the memory index"),
            ],
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        from birkin.memory.wiki import WikiMemory

        category = args.get("category", "")
        slug = args.get("slug", "")

        if not category or not slug:
            return ToolOutput(success=False, output="", error="Both 'category' and 'slug' are required")

        wiki = WikiMemory(root="./memory")
        content = wiki.get_page(category, slug)

        if content is None:
            return ToolOutput(
                success=False,
                output="",
                error=f"Page not found: {category}/{slug}",
            )

        # Bump reference tracking
        wiki.touch_page(category, slug)

        return ToolOutput(
            success=True,
            output=content[:5000],
            metadata={"category": category, "slug": slug, "chars": len(content)},
        )
