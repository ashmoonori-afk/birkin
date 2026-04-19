"""Profile compiler — analyze imported conversations to build user profile wiki pages.

Takes parsed conversations from ChatGPT/Claude exports, sends them to an LLM
in batches for analysis, then merges results and writes structured wiki pages.
"""

from __future__ import annotations

import json
import logging
import re as _re
import unicodedata as _ud
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from birkin.memory.importers.base import ParsedConversation
from birkin.memory.wiki import WikiMemory

logger = logging.getLogger(__name__)

# Maximum characters per user message to include in batch analysis
_MAX_MSG_CHARS = 500
# Maximum user messages per conversation to include
_MAX_MSGS_PER_CONV = 10

_BATCH_ANALYSIS_PROMPT = """\
You are analyzing a batch of user conversations to extract a profile of the user.
Focus ONLY on what the user reveals about themselves — their questions, requests,
and statements. Ignore the assistant's responses.

Extract the following from the conversations below:
- job_role: What is the user's job or role? (string or null)
- expertise_areas: What domains does the user have expertise in? (list of strings)
- interests: What topics interest the user? (list of strings)
- active_projects: What projects is the user working on? (list of strings)
- tools_and_tech: What tools, languages, or technologies does the user use? (list of strings)
- decision_patterns: How does the user make decisions? Any recurring patterns? (list of strings)
- communication_style: How does the user communicate? Formal/casual, verbose/concise, etc. (string or null)
- key_people: People the user mentions or works with (list of strings)

Rules:
- Only include what is explicitly mentioned or strongly implied
- Do NOT speculate or hallucinate
- Support bilingual content (Korean and English)
- Return valid JSON only, no markdown fences

Conversations:
{conversations}
"""

_MERGE_PROMPT = """\
You are merging multiple analysis batches into a single coherent user profile.
Each batch below analyzed a subset of the user's conversations.

Merge them into ONE unified profile. Deduplicate, resolve conflicts (later batches
are more recent), and rank items by frequency/confidence.

Batch results:
{batches}

Return a single JSON object with these fields:
- job_role: string or null
- expertise_areas: list of strings (ranked by confidence, max 15)
- interests: list of strings (max 15)
- active_projects: list of strings (max 10)
- tools_and_tech: list of strings (max 15)
- decision_patterns: list of strings (max 5)
- communication_style: string or null
- key_people: list of strings (max 10)

Rules:
- Deduplicate similar items (e.g., "Python" and "python" → "Python")
- Prefer more specific descriptions over vague ones
- Return valid JSON only, no markdown fences
"""


@dataclass
class ProfileCompileResult:
    """Result of profile compilation."""

    pages_created: list[str] = field(default_factory=list)
    batches_total: int = 0
    batches_succeeded: int = 0
    batches_failed: int = 0
    conversations_processed: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ProgressInfo:
    """Progress update during compilation."""

    phase: str  # "parsing", "analyzing", "merging", "compiling"
    current: int
    total: int


class ProfileCompiler:
    """Compile user profile from imported conversations via LLM analysis."""

    def __init__(self, provider: Any, memory: WikiMemory) -> None:
        self._provider = provider
        self._memory = memory

    def compile_profile(
        self,
        conversations: list[ParsedConversation],
        *,
        batch_size: int = 50,
        max_conversations: int = 500,
        on_progress: Optional[Callable[[ProgressInfo], None]] = None,
    ) -> ProfileCompileResult:
        """Analyze conversations and compile into wiki profile pages.

        Args:
            conversations: Parsed conversations from any importer.
            batch_size: Number of conversations per LLM analysis batch.
            max_conversations: Maximum conversations to process.
            on_progress: Optional callback for progress updates.

        Returns:
            ProfileCompileResult with created pages and statistics.
        """
        result = ProfileCompileResult()

        # Cap to max
        convs = conversations[:max_conversations]
        result.conversations_processed = len(convs)

        if not convs:
            return result

        # Phase 1: Batch analysis
        batches = [convs[i : i + batch_size] for i in range(0, len(convs), batch_size)]
        result.batches_total = len(batches)
        batch_results: list[dict[str, Any]] = []

        for i, batch in enumerate(batches):
            if on_progress:
                on_progress(ProgressInfo(phase="analyzing", current=i + 1, total=len(batches)))

            try:
                batch_profile = self._analyze_batch(batch)
                if batch_profile:
                    batch_results.append(batch_profile)
                    result.batches_succeeded += 1
                else:
                    result.batches_failed += 1
                    result.errors.append(f"Batch {i + 1}: empty LLM response")
            except Exception as exc:
                result.batches_failed += 1
                result.errors.append(f"Batch {i + 1}: {exc!s}")
                logger.warning("Batch %d failed: %s", i + 1, exc)

        if not batch_results:
            result.errors.append("All batches failed — no profile data extracted")
            return result

        # Phase 2: Merge batch results
        if on_progress:
            on_progress(ProgressInfo(phase="merging", current=1, total=1))

        if len(batch_results) == 1:
            merged = batch_results[0]
        else:
            try:
                merged = self._merge_batches(batch_results)
            except Exception as exc:
                logger.warning("Merge failed, using first batch: %s", exc)
                result.errors.append(f"Merge failed: {exc!s}")
                merged = batch_results[0]

        # Phase 3: Write wiki pages
        if on_progress:
            on_progress(ProgressInfo(phase="compiling", current=1, total=1))

        pages = self._write_profile_pages(merged)
        result.pages_created = pages

        return result

    def _analyze_batch(self, batch: list[ParsedConversation]) -> Optional[dict[str, Any]]:
        """Send a batch of conversations to LLM for analysis."""
        # Build conversation summaries — user messages only
        conv_texts: list[str] = []
        for conv in batch:
            user_msgs = conv.user_messages[:_MAX_MSGS_PER_CONV]
            if not user_msgs:
                continue
            lines = [f"[{conv.title}]"]
            for msg in user_msgs:
                text = msg.content[:_MAX_MSG_CHARS]
                lines.append(f"  User: {text}")
            conv_texts.append("\n".join(lines))

        if not conv_texts:
            return None

        prompt = _BATCH_ANALYSIS_PROMPT.format(conversations="\n\n".join(conv_texts))

        from birkin.core.providers.base import Message

        messages = [Message(role="user", content=prompt)]
        response = self._provider.complete(messages)

        return self._parse_json_response(response.content or "")

    def _merge_batches(self, batch_results: list[dict[str, Any]]) -> dict[str, Any]:
        """Merge multiple batch analysis results into a single profile."""
        batches_text = "\n\n".join(json.dumps(b, ensure_ascii=False) for b in batch_results)
        prompt = _MERGE_PROMPT.format(batches=batches_text)

        from birkin.core.providers.base import Message

        messages = [Message(role="user", content=prompt)]
        response = self._provider.complete(messages)

        result = self._parse_json_response(response.content or "")
        if result is None:
            raise ValueError("LLM returned unparseable response during merge")
        return result

    def _write_profile_pages(self, profile: dict[str, Any]) -> list[str]:
        """Write granular profile pages with [[wikilink]] connections."""
        pages: list[str] = []
        slug_map: dict[str, str] = {}  # display_name -> slug

        # -- 1. Individual project pages (concepts/project-*) ----------------
        projects = profile.get("active_projects", [])
        for proj in projects:
            slug = _slugify(f"project-{proj}")
            slug_map[proj] = slug
            self._memory.ingest(
                "concepts",
                slug,
                f"# {proj}\n\nActive project.",
                tags=["profile", "project", "imported"],
                source="conversation_import",
            )
            pages.append(f"concepts/{slug}")

        # -- 2. Individual tool pages (concepts/tool-*) ----------------------
        tools = profile.get("tools_and_tech", [])
        for tool in tools:
            slug = _slugify(f"tool-{tool}")
            slug_map[tool] = slug
            self._memory.ingest(
                "concepts",
                slug,
                f"# {tool}\n\nTool / technology used.",
                tags=["profile", "tool", "imported"],
                source="conversation_import",
            )
            pages.append(f"concepts/{slug}")

        # -- 3. Individual skill pages (concepts/skill-*) --------------------
        expertise = profile.get("expertise_areas", [])
        for skill in expertise:
            slug = _slugify(f"skill-{skill}")
            slug_map[skill] = slug
            # Link to related projects & tools via keyword overlap
            links = _find_related(skill, projects + tools, slug_map)
            body = f"# {skill}\n\nExpertise area."
            if links:
                body += "\n\n## Related\n" + "\n".join(f"- [[{s}]]" for s in links)
            self._memory.ingest(
                "concepts",
                slug,
                body,
                tags=["profile", "skill", "imported"],
                source="conversation_import",
            )
            pages.append(f"concepts/{slug}")

        # -- 4. Individual person pages (entities/person-*) ------------------
        people = profile.get("key_people", [])
        for person in people:
            slug = _slugify(f"person-{person}")
            slug_map[person] = slug
            links = _find_related(person, projects, slug_map)
            body = f"# {person}\n\nKey contact."
            if links:
                body += "\n\n## Related\n" + "\n".join(f"- [[{s}]]" for s in links)
            self._memory.ingest(
                "entities",
                slug,
                body,
                tags=["profile", "person", "imported"],
                source="conversation_import",
            )
            pages.append(f"entities/{slug}")

        # -- 5. Interest pages (concepts/interest-*) -------------------------
        interests = profile.get("interests", [])
        for interest in interests:
            slug = _slugify(f"interest-{interest}")
            slug_map[interest] = slug
            links = _find_related(interest, projects + tools, slug_map)
            body = f"# {interest}\n\nArea of interest."
            if links:
                body += "\n\n## Related\n" + "\n".join(f"- [[{s}]]" for s in links)
            self._memory.ingest(
                "concepts",
                slug,
                body,
                tags=["profile", "interest", "imported"],
                source="conversation_import",
            )
            pages.append(f"concepts/{slug}")

        # -- 6. Decision patterns (single page, links to projects) -----------
        patterns = profile.get("decision_patterns", [])
        if patterns:
            proj_links = [f"[[{slug_map[p]}]]" for p in projects if p in slug_map]
            body = "# Decision Patterns\n\n"
            body += "\n".join(f"- {p}" for p in patterns)
            if proj_links:
                body += "\n\n## Applied in\n" + "\n".join(f"- {lk}" for lk in proj_links)
            self._memory.ingest(
                "concepts",
                "user-patterns",
                body,
                tags=["profile", "patterns", "imported"],
                source="conversation_import",
            )
            pages.append("concepts/user-patterns")

        # -- 7. Communication style (single page) ---------------------------
        style = profile.get("communication_style")
        if style:
            self._memory.ingest(
                "concepts",
                "user-style",
                f"# Communication Style\n\n{style}",
                tags=["profile", "style", "imported"],
                source="conversation_import",
            )
            pages.append("concepts/user-style")

        # -- 8. Hub page: user-profile (links to everything) -----------------
        job_role = profile.get("job_role", "Unknown")
        hub = ["# User Profile\n", f"**Role:** {job_role}\n"]

        if expertise:
            hub.append("## Expertise")
            hub.extend(f"- [[{slug_map[s]}]]" for s in expertise if s in slug_map)
        if projects:
            hub.append("\n## Projects")
            hub.extend(f"- [[{slug_map[p]}]]" for p in projects if p in slug_map)
        if tools:
            hub.append("\n## Tools & Tech")
            hub.extend(f"- [[{slug_map[t]}]]" for t in tools if t in slug_map)
        if people:
            hub.append("\n## Key People")
            hub.extend(f"- [[{slug_map[p]}]]" for p in people if p in slug_map)
        if interests:
            hub.append("\n## Interests")
            hub.extend(f"- [[{slug_map[i]}]]" for i in interests if i in slug_map)
        if patterns:
            hub.append("\n## Decision Patterns → [[user-patterns]]")
        if style:
            hub.append("\n## Communication → [[user-style]]")

        self._memory.ingest(
            "entities",
            "user-profile",
            "\n".join(hub),
            tags=["profile", "hub", "imported"],
            source="conversation_import",
        )
        pages.append("entities/user-profile")

        return pages

    @staticmethod
    def _parse_json_response(text: str) -> Optional[dict[str, Any]]:
        """Parse JSON from LLM response, handling markdown fences."""
        text = text.strip()
        # Remove markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Skip first line (```json) and last line (```)
            lines = [ln for ln in lines[1:] if ln.strip() != "```"]
            text = "\n".join(lines)

        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM JSON response: %s", text[:200])

        return None


# ---------------------------------------------------------------------------
# Helpers for graph-based profile pages
# ---------------------------------------------------------------------------


def _slugify(text: str, max_len: int = 60) -> str:
    """Turn a display name into a URL-safe slug for wiki pages.

    Keeps Korean characters, lowercases Latin, replaces whitespace/symbols
    with hyphens.
    """
    text = text.strip()
    # Remove parenthetical notes like "(GitHub: ...)"
    text = _re.sub(r"\(.*?\)", "", text).strip()
    text = _ud.normalize("NFC", text)
    text = _re.sub(r"[\s/\\,;:]+", "-", text)
    text = _re.sub(r"[^\w가-힣-]", "", text)
    text = _re.sub(r"-{2,}", "-", text).strip("-")
    text = text.lower()
    return text[:max_len] or "unnamed"


def _find_related(
    name: str,
    candidates: list[str],
    slug_map: dict[str, str],
    min_overlap: int = 2,
) -> list[str]:
    """Find candidates sharing keywords with *name*. Return their slugs."""
    name_words = {w.lower() for w in _re.split(r"[\s/,()]+", name) if len(w) > 1}
    related: list[str] = []
    for cand in candidates:
        if cand == name:
            continue
        cand_words = {w.lower() for w in _re.split(r"[\s/,()]+", cand) if len(w) > 1}
        if len(name_words & cand_words) >= min_overlap and cand in slug_map:
            related.append(slug_map[cand])
    return related
