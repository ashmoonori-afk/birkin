"""LLM-powered natural language workflow builder.

Uses a Provider to convert free-text descriptions into validated
workflow graph definitions compatible with WorkflowEngine.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from birkin.core.models import Message
from birkin.core.providers.base import Provider

logger = logging.getLogger(__name__)

# Valid node types pulled from WorkflowEngine._NODE_HANDLERS
VALID_NODE_TYPES: frozenset[str] = frozenset(
    [
        # I/O
        "input",
        "output",
        "webhook-trigger",
        "merge",
        "parallel",
        # AI models
        "llm",
        "llm-stream",
        "classifier",
        "embedder",
        "summarizer",
        "translator",
        "knowledge-extract",
        # Tools
        "tool-dispatch",
        "web-search",
        "code-exec",
        "shell",
        "api-call",
        "file-read",
        "file-write",
        # Memory
        "memory-search",
        "memory-write",
        "context-inject",
        # Control flow
        "condition",
        "loop",
        "delay",
        "prompt-template",
        # Quality gates
        "code-review",
        "human-review",
        "guardrail",
        "validator",
        "test-runner",
        # Platform
        "hn-fetch",
        "telegram-send",
        "email-send",
        "notify",
        # Control flow extensions
        "switch",
        "for-each",
        "try-catch",
        "cron-trigger",
        # Data transformation
        "csv-parse",
        "json-transform",
        "pdf-extract",
        "data-format",
        # Scheduling
        "datetime",
        "rate-limit",
        # Communication
        "slack-send",
        "discord-send",
        "sms-send",
        "webhook-send",
        "email-read",
        # Image & media
        "image-resize",
        "image-generate",
        "vision-analyze",
        "audio-transcribe",
        # Database
        "db-query",
        "db-write",
        "cloud-storage",
        # Web & RSS
        "rss-fetch",
        "web-scrape",
        "html-parse",
        # Calendar & tasks
        "calendar-event",
        "task-create",
        # Document generation
        "pdf-generate",
        "spreadsheet-write",
        # Security
        "secret-inject",
    ]
)


class WorkflowNode(BaseModel):
    """A single node in a workflow graph."""

    id: str
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdge(BaseModel):
    """A directed edge between two nodes."""

    from_node: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


class WorkflowGraphOutput(BaseModel):
    """Complete workflow graph matching WorkflowEngine format."""

    name: str = ""
    description: str = ""
    mode: str = "graph"
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)

    def to_engine_dict(self) -> dict[str, Any]:
        """Export as a dict loadable by WorkflowEngine.load()."""
        return {
            "name": self.name,
            "description": self.description,
            "mode": self.mode,
            "nodes": [{"id": n.id, "type": n.type, "config": n.config} for n in self.nodes],
            "edges": [{"from": e.from_node, "to": e.to} for e in self.edges],
        }


_SORTED_TYPES = sorted(VALID_NODE_TYPES)

SYSTEM_PROMPT = f"""\
You are a workflow graph generator for the Birkin automation platform.
Given a natural language description (Korean or English), produce a JSON
workflow graph that can be executed by WorkflowEngine.

## Valid node types

{json.dumps(_SORTED_TYPES, indent=2)}

## Output JSON schema

Return ONLY valid JSON (no markdown fences, no explanation) with this structure:

{{
  "name": "<short-kebab-case-name>",
  "description": "<original user description>",
  "mode": "graph",
  "nodes": [
    {{"id": "<unique-id>", "type": "<valid-node-type>", "config": {{...}}}}
  ],
  "edges": [
    {{"from": "<source-node-id>", "to": "<target-node-id>"}}
  ]
}}

## Rules
- Every node "type" MUST be one of the valid node types listed above.
- The first node should be "input" and the last edge should point to "__end__".
- Node ids should be descriptive kebab-case strings.
- config should contain relevant parameters (instruction, template, url, etc.).

## Examples

### English
User: "Summarize a web page and send the result to Telegram"
{{
  "name": "summarize-and-notify",
  "description": "Summarize a web page and send the result to Telegram",
  "mode": "graph",
  "nodes": [
    {{"id": "start", "type": "input", "config": {{}}}},
    {{"id": "fetch-page", "type": "web-search", "config": {{"instruction": "fetch the web page"}}}},
    {{"id": "summarize", "type": "summarizer", "config": {{}}}},
    {{"id": "send-telegram", "type": "telegram-send", "config": {{}}}}
  ],
  "edges": [
    {{"from": "start", "to": "fetch-page"}},
    {{"from": "fetch-page", "to": "summarize"}},
    {{"from": "summarize", "to": "send-telegram"}},
    {{"from": "send-telegram", "to": "__end__"}}
  ]
}}

### Korean
User: "파일을 읽고 번역한 뒤 이메일로 보내줘"
{{
  "name": "read-translate-email",
  "description": "파일을 읽고 번역한 뒤 이메일로 보내줘",
  "mode": "graph",
  "nodes": [
    {{"id": "start", "type": "input", "config": {{}}}},
    {{"id": "read-file", "type": "file-read", "config": {{}}}},
    {{"id": "translate", "type": "translator", "config": {{"target_language": "English"}}}},
    {{"id": "send-email", "type": "email-send", "config": {{}}}}
  ],
  "edges": [
    {{"from": "start", "to": "read-file"}},
    {{"from": "read-file", "to": "translate"}},
    {{"from": "translate", "to": "send-email"}},
    {{"from": "send-email", "to": "__end__"}}
  ]
}}
"""


def _extract_json(text: str) -> str:
    """Extract JSON from LLM response, stripping markdown fences if present."""
    # Try to find JSON in markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Try to find raw JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0).strip()
    return text.strip()


def validate_node_types(graph: dict[str, Any]) -> list[str]:
    """Return list of invalid node types found in the graph."""
    invalid = []
    for node in graph.get("nodes", []):
        ntype = node.get("type", "")
        if ntype not in VALID_NODE_TYPES:
            invalid.append(ntype)
    return invalid


class LLMWorkflowBuilder:
    """Generates workflow graphs using an LLM provider.

    Falls back to keyword-based NLWorkflowBuilder on failure.

    Usage::

        builder = LLMWorkflowBuilder(provider)
        graph = await builder.generate("summarize this page and email it")
    """

    def __init__(self, provider: Provider) -> None:
        self._provider = provider

    async def generate(self, description: str) -> dict[str, Any]:
        """Generate a workflow graph from a natural language description.

        Calls the LLM provider with a structured system prompt, parses
        the JSON response, and validates node types. Falls back to the
        keyword builder if LLM generation fails.

        Args:
            description: Free-text description of the desired workflow.

        Returns:
            Workflow graph dict loadable by WorkflowEngine.load().
        """
        try:
            return await self._generate_via_llm(description)
        except (ValueError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            logger.warning(
                "LLM workflow generation failed (%s), falling back to keyword builder",
                exc,
            )
            return self._fallback(description)

    async def _generate_via_llm(self, description: str) -> dict[str, Any]:
        """Call LLM and parse + validate the response."""
        messages = [
            Message(role="system", content=SYSTEM_PROMPT),
            Message(role="user", content=description),
        ]
        response = await self._provider.acomplete(messages)
        raw = response.content or ""

        if not raw.strip():
            raise ValueError("Empty LLM response")

        json_str = _extract_json(raw)
        graph = json.loads(json_str)

        # Validate structure
        if not isinstance(graph, dict):
            raise ValueError("LLM response is not a JSON object")
        if "nodes" not in graph or "edges" not in graph:
            raise ValueError("Missing 'nodes' or 'edges' in LLM response")

        # Validate node types
        invalid = validate_node_types(graph)
        if invalid:
            raise ValueError(f"Invalid node types: {invalid}")

        # Ensure required fields
        graph.setdefault("name", "llm-generated")
        graph.setdefault("description", description)
        graph.setdefault("mode", "graph")

        return graph

    @staticmethod
    def _fallback(description: str) -> dict[str, Any]:
        """Use keyword-based builder as fallback."""
        from birkin.core.workflow.nl_builder import NLWorkflowBuilder

        builder = NLWorkflowBuilder()
        draft = builder.generate(description)
        return draft.to_graph_json()
