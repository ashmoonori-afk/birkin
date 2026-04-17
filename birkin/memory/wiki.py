"""LLM Wiki memory backend — persistent markdown-based knowledge store.

Follows the compilation-over-retrieval pattern: knowledge is compiled into
wiki pages once and maintained incrementally, not re-derived on every query.
All storage is plain markdown files — no vector DB, no infrastructure.
"""

from __future__ import annotations

import datetime as dt
import re
import threading
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
        self._lock = threading.RLock()

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
        with self._lock:
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

    # Prompt injection patterns to detect and neutralize
    _INJECTION_PATTERNS = [
        "ignore previous",
        "ignore all previous",
        "you are now",
        "[SYSTEM]",
        "<<SYS>>",
        "new instructions:",
        "override:",
        "disregard",
    ]

    def _sanitize_content(self, content: str) -> str:
        """Detect and neutralize prompt injection patterns in memory content.

        Wraps suspicious instruction-like content in code blocks so it
        cannot be interpreted as system instructions.
        """
        content_lower = content.lower()
        for pattern in self._INJECTION_PATTERNS:
            if pattern.lower() in content_lower:
                # Don't flag content already inside code blocks
                in_code = False
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    if line.strip().startswith("```"):
                        in_code = not in_code
                    if not in_code and pattern.lower() in line.lower():
                        lines[i] = f"`{line}`"
                content = "\n".join(lines)
                break
        return content

    def ingest(
        self,
        category: str,
        slug: str,
        content: str,
        *,
        tags: Optional[list[str]] = None,
        source: str = "auto_classified",
        auto_link: bool = False,
    ) -> Path:
        """Write or overwrite a wiki page and update index + log.

        Parameters
        ----------
        category : str
            One of ``"entities"``, ``"concepts"``, ``"sessions"``, ``"decisions"``,
            ``"patterns"``, or ``"digests"``.
        slug : str
            Filename stem (e.g. ``"python-asyncio"``).
        content : str
            Full markdown body for the page.
        tags : list[str], optional
            Tags to embed as frontmatter for search/graph.
        auto_link : bool
            If True, auto-insert [[wikilinks]] after saving.

        Returns
        -------
        Path
            Absolute path to the written file.
        """
        with self._lock:
            self.init()  # ensure dirs exist

            # Sanitize against prompt injection
            content = self._sanitize_content(content)

            # Prepend frontmatter (tags + source) if not already present
            if not content.startswith("---"):
                fm_lines = []
                if tags:
                    fm_lines.append("tags: " + ", ".join(tags))
                fm_lines.append(f"source: {source}")
                if fm_lines:
                    content = "---\n" + "\n".join(fm_lines) + "\n---\n\n" + content

            page_path = self.wiki_dir / category / f"{slug}.md"
            is_update = page_path.exists()
            page_path.write_text(content, encoding="utf-8")

            self._update_index()
            action = "updated" if is_update else "created"
            self._append_log(f"{action} {category}/{slug}.md")

            # Auto-link after ingest so new pages connect to existing ones
            if auto_link:
                self.auto_link()

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
        with self._lock:
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

    # Slugs shorter than this are too generic to auto-link (e.g. "prompt", "study")
    _MIN_AUTOLINK_SLUG_LEN = 4
    # Max links to insert per page to prevent spam
    _MAX_LINKS_PER_PAGE = 10

    def auto_link(self) -> int:
        """Scan all pages and auto-insert [[wikilinks]] where page slugs appear in text.

        Safety guards:
        - Slugs shorter than 6 chars are skipped (too generic)
        - Max 10 new links per page
        - Only first occurrence of each slug is linked per page
        - Code blocks and frontmatter are excluded

        Returns the number of links added.
        """
        with self._lock:
            pages = self.list_pages()
            # Filter out short/generic slugs
            linkable_slugs = [
                p["slug"] for p in pages if len(p["slug"]) >= self._MIN_AUTOLINK_SLUG_LEN
            ]

            if not linkable_slugs:
                return 0

            links_added = 0

            for page in pages:
                cat = page["category"]
                slug = page["slug"]
                page_path = self.wiki_dir / cat / f"{slug}.md"
                if not page_path.is_file():
                    continue

                content = page_path.read_text(encoding="utf-8")
                modified = content
                page_links = 0

                for target_slug in linkable_slugs:
                    if target_slug == slug:
                        continue  # Don't self-link
                    if page_links >= self._MAX_LINKS_PER_PAGE:
                        break

                    # Match slug NOT inside [[ ]], code blocks, or frontmatter
                    # Only replace first occurrence (count=1)
                    pattern = re.compile(
                        r"(?<!\[\[)\b(" + re.escape(target_slug) + r")\b(?!\]\])",
                    )

                    new_content, count = pattern.subn(
                        lambda m: f"[[{m.group(1)}]]", modified, count=1
                    )
                    if count > 0:
                        links_added += count
                        page_links += count
                        modified = new_content

                if modified != content:
                    page_path.write_text(modified, encoding="utf-8")

            return links_added

    def summarize_old_sessions(self, max_age_hours: int = 24) -> list[str]:
        """Find session pages older than max_age_hours, merge them into a summary page,
        and delete the originals.

        Returns list of deleted slugs.
        """
        with self._lock:
            self.init()
            sessions_dir = self.wiki_dir / "sessions"
            if not sessions_dir.is_dir():
                return []

            now = dt.datetime.now(dt.timezone.utc)
            cutoff = now - dt.timedelta(hours=max_age_hours)
            cutoff_ts = cutoff.timestamp()

            # Collect old session files grouped by date
            old_sessions: dict[str, list[tuple[str, str]]] = {}  # date_str -> [(slug, content)]
            deleted_slugs: list[str] = []

            for md_file in sorted(sessions_dir.glob("*.md")):
                mtime = md_file.stat().st_mtime
                if mtime < cutoff_ts:
                    slug = md_file.stem
                    content = md_file.read_text(encoding="utf-8")
                    # Group by date from file modification time
                    date_str = dt.datetime.fromtimestamp(mtime, tz=dt.timezone.utc).strftime("%Y-%m-%d")
                    if date_str not in old_sessions:
                        old_sessions[date_str] = []
                    old_sessions[date_str].append((slug, content))
                    deleted_slugs.append(slug)

            if not old_sessions:
                return []

            # Create summary pages and delete originals
            for date_str, sessions in old_sessions.items():
                summary_slug = f"summary-{date_str}"
                parts = [f"# Session Summary ({date_str})\n"]
                for slug, content in sessions:
                    parts.append(f"## {slug}\n\n{content}\n\n---\n")
                summary_content = "\n".join(parts)
                self.ingest("concepts", summary_slug, summary_content)

                # Delete original session pages
                for slug, _ in sessions:
                    self.delete_page("sessions", slug)

            return deleted_slugs

    def _append_log(self, entry: str) -> None:
        """Append a timestamped entry to log.md."""
        log_path = self.wiki_dir / "log.md"
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n- [{timestamp}] {entry}")
