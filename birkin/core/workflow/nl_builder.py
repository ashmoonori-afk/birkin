"""Natural language workflow builder — description to graph workflow.

Parses a natural language description of an automation and generates
a workflow graph definition that can be loaded into the StateGraph engine.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from birkin.core.providers.base import Provider

logger = logging.getLogger(__name__)


class WorkflowStep(BaseModel):
    """A single step in a generated workflow."""

    name: str
    node_type: str  # "llm_call", "tool_call", "condition", "notify", etc.
    config: dict[str, Any] = {}
    next_step: Optional[str] = None


class WorkflowDraft(BaseModel):
    """Generated workflow from natural language description."""

    name: str = ""
    description: str = ""
    steps: list[WorkflowStep] = Field(default_factory=list)
    trigger: Optional[dict[str, Any]] = None
    review_notes: list[str] = Field(default_factory=list)

    def to_graph_json(self) -> dict[str, Any]:
        """Export as a JSON-compatible graph definition."""
        nodes = []
        edges = []
        for i, step in enumerate(self.steps):
            nodes.append(
                {
                    "id": step.name,
                    "type": step.node_type,
                    "config": step.config,
                }
            )
            next_name = step.next_step or (self.steps[i + 1].name if i + 1 < len(self.steps) else "__end__")
            edges.append({"from": step.name, "to": next_name})

        return {
            "name": self.name,
            "description": self.description,
            "mode": "graph",
            "nodes": nodes,
            "edges": edges,
            "trigger": self.trigger,
        }


# Keyword patterns for step type detection
_STEP_PATTERNS: list[tuple[str, list[str]]] = [
    ("llm_call", ["summarize", "analyze", "generate", "write", "translate", "요약", "분석", "작성"]),
    ("tool_call", ["search", "fetch", "scrape", "download", "read file", "검색", "가져와"]),
    ("notify", ["send", "notify", "email", "telegram", "slack", "discord", "sms", "알림", "보내"]),
    ("condition", ["if ", "when ", "check ", "만약", "확인"]),
    ("schedule", ["every ", "daily", "weekly", "매일", "매주", "cron"]),
    ("data", ["csv", "json", "spreadsheet", "excel", "pdf", "데이터", "변환"]),
    ("database", ["database", "sql", "query", "db", "데이터베이스", "쿼리"]),
    ("media", ["image", "resize", "transcribe", "audio", "vision", "이미지", "음성"]),
    ("web", ["rss", "feed", "scrape", "crawl", "피드", "크롤링"]),
    ("task", ["task", "todo", "calendar", "할일", "일정"]),
]


class NLWorkflowBuilder:
    """Generates workflow graphs from natural language descriptions.

    Uses keyword-based parsing for offline operation. Can be extended
    with LLM-based generation for higher quality.

    Usage::

        builder = NLWorkflowBuilder()
        draft = builder.generate("every morning summarize calendar and send to telegram")
    """

    def generate(self, description: str) -> WorkflowDraft:
        """Generate a workflow draft from a natural language description.

        Args:
            description: Free-text description of the desired workflow.

        Returns:
            WorkflowDraft with steps, trigger, and review notes.
        """
        description = description.strip()
        steps: list[WorkflowStep] = []
        trigger: Optional[dict[str, Any]] = None
        review_notes: list[str] = []

        # Split into logical parts by "and", "then", commas
        parts = re.split(r"\s*(?:,\s*|\s+(?:and|then)\s+)", description, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if p.strip()]

        for i, part in enumerate(parts):
            step_type = self._detect_step_type(part)
            step_name = f"step_{i + 1}_{step_type}"

            if step_type == "schedule":
                trigger = {"type": "cron", "description": part}
                review_notes.append(f"Schedule detected: '{part}' — configure cron expression manually")
                continue

            steps.append(
                WorkflowStep(
                    name=step_name,
                    node_type=step_type,
                    config={"instruction": part},
                )
            )

        if not steps:
            steps.append(
                WorkflowStep(
                    name="step_1_llm_call",
                    node_type="llm_call",
                    config={"instruction": description},
                )
            )
            review_notes.append("Could not parse specific steps — wrapped entire description as single LLM call")

        # Generate a name from description
        name_words = re.sub(r"[^a-zA-Z0-9\s]", "", description.lower()).split()[:4]
        name = "-".join(name_words) if name_words else "generated-workflow"

        return WorkflowDraft(
            name=name,
            description=description,
            steps=steps,
            trigger=trigger,
            review_notes=review_notes,
        )

    @staticmethod
    def _detect_step_type(text: str) -> str:
        """Detect the step type from text using keyword matching."""
        text_lower = text.lower()
        for step_type, keywords in _STEP_PATTERNS:
            for kw in keywords:
                if kw in text_lower:
                    return step_type
        return "llm_call"  # default


async def build_workflow(
    description: str,
    provider: Optional[Provider] = None,
) -> dict[str, Any]:
    """Facade: generate a workflow graph from natural language.

    If a *provider* is given, uses :class:`LLMWorkflowBuilder` for
    higher-quality generation.  Otherwise falls back to the keyword-based
    :class:`NLWorkflowBuilder`.

    Args:
        description: Free-text description of the desired workflow.
        provider: Optional LLM provider for LLM-powered generation.

    Returns:
        Workflow graph dict loadable by ``WorkflowEngine.load()``.
    """
    if provider is not None:
        from birkin.core.workflow.nl_builder_llm import LLMWorkflowBuilder

        builder = LLMWorkflowBuilder(provider)
        return await builder.generate(description)

    keyword_builder = NLWorkflowBuilder()
    draft = keyword_builder.generate(description)
    return draft.to_graph_json()
