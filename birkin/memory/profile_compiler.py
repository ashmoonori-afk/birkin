"""Profile compiler — analyze imported conversations to build user profile wiki pages.

Takes parsed conversations from ChatGPT/Claude exports, sends them to an LLM
in batches for analysis, then merges results and writes structured wiki pages.
"""

from __future__ import annotations

import json
import logging
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
        """Write the merged profile data into wiki pages."""
        pages_created: list[str] = []

        # 1. User Profile (entities)
        job_role = profile.get("job_role", "Unknown")
        key_people = profile.get("key_people", [])
        parts = ["# User Profile\n"]
        parts.append(f"**Role:** {job_role}\n")
        if key_people:
            parts.append("## Key People\n")
            for person in key_people:
                parts.append(f"- {person}")
        self._memory.ingest(
            "entities",
            "user-profile",
            "\n".join(parts),
            tags=["profile", "imported"],
            source="conversation_import",
        )
        pages_created.append("entities/user-profile")

        # 2. Expertise (concepts)
        expertise = profile.get("expertise_areas", [])
        if expertise:
            parts = ["# User Expertise\n"]
            for area in expertise:
                parts.append(f"- {area}")
            self._memory.ingest(
                "concepts",
                "user-expertise",
                "\n".join(parts),
                tags=["profile", "expertise", "imported"],
                source="conversation_import",
            )
            pages_created.append("concepts/user-expertise")

        # 3. Interests (concepts)
        interests = profile.get("interests", [])
        if interests:
            parts = ["# User Interests\n"]
            for interest in interests:
                parts.append(f"- {interest}")
            self._memory.ingest(
                "concepts",
                "user-interests",
                "\n".join(parts),
                tags=["profile", "interests", "imported"],
                source="conversation_import",
            )
            pages_created.append("concepts/user-interests")

        # 4. Projects (concepts)
        projects = profile.get("active_projects", [])
        if projects:
            parts = ["# User Projects\n"]
            for proj in projects:
                parts.append(f"- {proj}")
            self._memory.ingest(
                "concepts",
                "user-projects",
                "\n".join(parts),
                tags=["profile", "projects", "imported"],
                source="conversation_import",
            )
            pages_created.append("concepts/user-projects")

        # 5. Decision Patterns (concepts)
        patterns = profile.get("decision_patterns", [])
        if patterns:
            parts = ["# Decision Patterns\n"]
            for p in patterns:
                parts.append(f"- {p}")
            self._memory.ingest(
                "concepts",
                "user-patterns",
                "\n".join(parts),
                tags=["profile", "patterns", "imported"],
                source="conversation_import",
            )
            pages_created.append("concepts/user-patterns")

        # 6. Communication Style (concepts)
        style = profile.get("communication_style")
        tools = profile.get("tools_and_tech", [])
        if style or tools:
            parts = ["# Communication Style\n"]
            if style:
                parts.append(f"{style}\n")
            if tools:
                parts.append("## Tools & Technologies\n")
                for t in tools:
                    parts.append(f"- {t}")
            self._memory.ingest(
                "concepts",
                "user-style",
                "\n".join(parts),
                tags=["profile", "style", "imported"],
                source="conversation_import",
            )
            pages_created.append("concepts/user-style")

        return pages_created

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
