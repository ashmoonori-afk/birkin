"""LLM Wiki memory backend — persistent markdown-based knowledge store.

Follows the compilation-over-retrieval pattern: knowledge is compiled into
wiki pages once and maintained incrementally, not re-derived on every query.
All storage is plain markdown files — no vector DB, no infrastructure.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Optional, Union

from birkin.core.defaults import DEFAULT_MEMORY_SCHEMA

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


class WikiMemory:
    """File-backed wiki memory with ingest, query, and lint operations.

    Parameters
    ----------
    root : Union[str, Path]
        Root directory for the memory store. Created on first write.
    schema : Optional[str]
        Optional override for the memory schema. Uses the Birkin default
        schema if not provided.
    """

    def __init__(self, root: Union[str, Path], *, schema: Optional[str] = None) -> None:
        self._root = Path(root)
        self._schema = schema or DEFAULT_MEMORY_SCHEMA

    @property
    def root(self) -> Path:
        return self._root

    @property
    def wiki_dir(self) -> Path:
        return self._root / "wiki"

    @property
    def raw_dir(self) -> Path:
        return self._root / "raw"

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Create the directory structure and seed files if they don't exist."""
        for d in (
            self._root,
            self.wiki_dir,
            self.wiki_dir / "entities",
            self.wiki_dir / "concepts",
            self.wiki_dir / "sessions",
            self.raw_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        schema_path = self._root / "schema.md"
        if not schema_path.exists():
            schema_path.write_text(self._schema, encoding="utf-8")

        index_path = self.wiki_dir / "index.md"
        if not index_path.exists():
            index_path.write_text("# Memory Index\n\nNo pages yet.\n", encoding="utf-8")

        log_path = self.wiki_dir / "log.md"
        if not log_path.exists():
            log_path.write_text(
                "# Memory Log\n\nAppend-only record of operations.\n",
                encoding="utf-8",
            )

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def ingest(self, category: str, slug: str, content: str) -> Path:
        """Write or overwrite a wiki page and update index + log.

        Parameters
        ----------
        category : str
            One of ``"entities"``, ``"concepts"``, or ``"sessions"``.
        slug : str
            Filename stem (e.g. ``"python-asyncio"``).
        content : str
            Full markdown body for the page.

        Returns
        -------
        Path
            Absolute path to the written file.
        """
        self.init()  # ensure dirs exist

        page_path = self.wiki_dir / category / f"{slug}.md"
        is_update = page_path.exists()
        page_path.write_text(content, encoding="utf-8")

        self._update_index()
        action = "updated" if is_update else "created"
        self._append_log(f"{action} {category}/{slug}.md")

        return page_path

    def query(self, term: str) -> list[dict[str, Any]]:
        """Search wiki pages for *term* (case-insensitive substring match).

        Returns a list of dicts with ``path``, ``category``, ``slug``, and
        a ``snippet`` showing the first matching line.
        """
        results: list[dict[str, Any]] = []
        pattern = re.compile(re.escape(term), re.IGNORECASE)

        for category in ("entities", "concepts", "sessions"):
            cat_dir = self.wiki_dir / category
            if not cat_dir.is_dir():
                continue
            for md_file in sorted(cat_dir.glob("*.md")):
                text = md_file.read_text(encoding="utf-8")
                match = pattern.search(text)
                if match:
                    # Extract the line containing the match
                    line_start = text.rfind("\n", 0, match.start()) + 1
                    line_end = text.find("\n", match.end())
                    if line_end == -1:
                        line_end = len(text)
                    snippet = text[line_start:line_end].strip()

                    results.append(
                        {
                            "path": str(md_file),
                            "category": category,
                            "slug": md_file.stem,
                            "snippet": snippet,
                        }
                    )
        return results

    def get_page(self, category: str, slug: str) -> Optional[str]:
        """Read a single wiki page. Returns ``None`` if it doesn't exist."""
        page_path = self.wiki_dir / category / f"{slug}.md"
        if page_path.is_file():
            return page_path.read_text(encoding="utf-8")
        return None

    def list_pages(self) -> list[dict[str, str]]:
        """Return metadata for every page in the wiki."""
        pages: list[dict[str, str]] = []
        for category in ("entities", "concepts", "sessions"):
            cat_dir = self.wiki_dir / category
            if not cat_dir.is_dir():
                continue
            for md_file in sorted(cat_dir.glob("*.md")):
                pages.append({"category": category, "slug": md_file.stem})
        return pages

    def delete_page(self, category: str, slug: str) -> bool:
        """Remove a wiki page. Returns True if it existed."""
        page_path = self.wiki_dir / category / f"{slug}.md"
        if page_path.is_file():
            page_path.unlink()
            self._update_index()
            self._append_log(f"deleted {category}/{slug}.md")
            return True
        return False

    def lint(self) -> list[str]:
        """Check for broken wikilinks and orphaned pages.

        Returns a list of human-readable warning strings.
        """
        warnings: list[str] = []
        all_slugs: set[str] = set()
        referenced_slugs: set[str] = set()

        for category in ("entities", "concepts", "sessions"):
            cat_dir = self.wiki_dir / category
            if not cat_dir.is_dir():
                continue
            for md_file in cat_dir.glob("*.md"):
                all_slugs.add(md_file.stem)
                text = md_file.read_text(encoding="utf-8")
                for link_match in _WIKILINK_RE.finditer(text):
                    target = link_match.group(1).strip()
                    referenced_slugs.add(target)

        # Broken links: referenced but not existing
        for ref in sorted(referenced_slugs - all_slugs):
            warnings.append(f"broken link: [[{ref}]] — page does not exist")

        # Orphans: existing but never referenced (excluding index/log)
        for orphan in sorted(all_slugs - referenced_slugs):
            warnings.append(f"orphaned page: {orphan} — not referenced by any page")

        return warnings

    # ------------------------------------------------------------------
    # Context builder (for injection into system prompt)
    # ------------------------------------------------------------------

    def build_context(self, max_pages: int = 10) -> str:
        """Build a concise memory context string for system prompt injection.

        Reads up to *max_pages* most recently modified pages and returns
        them as a single string block suitable for appending to a system prompt.
        """
        if not self.wiki_dir.is_dir():
            return ""

        pages: list[tuple[float, Path]] = []
        for category in ("entities", "concepts", "sessions"):
            cat_dir = self.wiki_dir / category
            if not cat_dir.is_dir():
                continue
            for md_file in cat_dir.glob("*.md"):
                pages.append((md_file.stat().st_mtime, md_file))

        if not pages:
            return ""

        # Sort by most recently modified, take top N
        pages.sort(key=lambda x: x[0], reverse=True)
        selected = pages[:max_pages]

        sections: list[str] = ["## Agent Memory (LLM Wiki)\n"]
        for _, page_path in selected:
            rel = page_path.relative_to(self.wiki_dir)
            text = page_path.read_text(encoding="utf-8").strip()
            # Truncate very long pages
            if len(text) > 2000:
                text = text[:2000] + "\n[...truncated]"
            sections.append(f"### {rel}\n{text}\n")

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_index(self) -> None:
        """Rewrite index.md from current wiki contents."""
        lines = ["# Memory Index\n"]
        for category in ("entities", "concepts", "sessions"):
            cat_dir = self.wiki_dir / category
            if not cat_dir.is_dir():
                continue
            files = sorted(cat_dir.glob("*.md"))
            if not files:
                continue
            lines.append(f"\n## {category.title()}\n")
            for md_file in files:
                # Read first non-heading, non-empty line as summary
                text = md_file.read_text(encoding="utf-8")
                summary = ""
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        summary = stripped[:120]
                        break
                lines.append(f"- [[{md_file.stem}]] — {summary}")

        index_path = self.wiki_dir / "index.md"
        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _append_log(self, entry: str) -> None:
        """Append a timestamped entry to log.md."""
        log_path = self.wiki_dir / "log.md"
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n- [{timestamp}] {entry}")
