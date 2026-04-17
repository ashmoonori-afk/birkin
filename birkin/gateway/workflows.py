"""Workflow persistence — save/load user-defined agent workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_WORKFLOWS_PATH = Path("birkin_workflows.json")

# 10 sample workflows
_SAMPLES: list[dict[str, Any]] = [
    {
        "id": "simple-chat",
        "name": "Simple Chat",
        "description": "Basic conversation without tools",
        "nodes": [
            {"id": "n1", "type": "input", "x": 80, "y": 200, "config": {}},
            {"id": "n2", "type": "llm", "x": 300, "y": 200, "config": {"model": "default"}},
            {"id": "n3", "type": "output", "x": 520, "y": 200, "config": {}},
        ],
        "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
    },
    {
        "id": "code-review-gate",
        "name": "Code Review Gate",
        "description": "Force human code review before final output",
        "nodes": [
            {"id": "n1", "type": "input", "x": 60, "y": 200, "config": {}},
            {
                "id": "n2",
                "type": "llm",
                "x": 240,
                "y": 200,
                "config": {"model": "default"},
            },
            {
                "id": "n3",
                "type": "code-review",
                "x": 420,
                "y": 200,
                "config": {"reviewer": "human"},
            },
            {"id": "n4", "type": "output", "x": 600, "y": 200, "config": {}},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4"},
        ],
    },
    {
        "id": "rag-pipeline",
        "name": "RAG Pipeline",
        "description": "Retrieve context from memory before generating",
        "nodes": [
            {"id": "n1", "type": "input", "x": 60, "y": 200, "config": {}},
            {"id": "n2", "type": "memory-search", "x": 240, "y": 200, "config": {}},
            {"id": "n3", "type": "context-inject", "x": 420, "y": 200, "config": {}},
            {"id": "n4", "type": "llm", "x": 600, "y": 200, "config": {}},
            {"id": "n5", "type": "output", "x": 780, "y": 200, "config": {}},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4"},
            {"from": "n4", "to": "n5"},
        ],
    },
    {
        "id": "multi-model-consensus",
        "name": "Multi-Model Consensus",
        "description": "Query multiple models and merge results",
        "nodes": [
            {"id": "n1", "type": "input", "x": 60, "y": 200, "config": {}},
            {
                "id": "n2",
                "type": "llm",
                "x": 280,
                "y": 100,
                "config": {"label": "Claude"},
            },
            {
                "id": "n3",
                "type": "llm",
                "x": 280,
                "y": 300,
                "config": {"label": "GPT"},
            },
            {"id": "n4", "type": "merge", "x": 480, "y": 200, "config": {}},
            {"id": "n5", "type": "output", "x": 660, "y": 200, "config": {}},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n1", "to": "n3"},
            {"from": "n2", "to": "n4"},
            {"from": "n3", "to": "n4"},
            {"from": "n4", "to": "n5"},
        ],
    },
    {
        "id": "safety-filter",
        "name": "Safety Filter",
        "description": "Content moderation before and after LLM",
        "nodes": [
            {"id": "n1", "type": "input", "x": 60, "y": 200, "config": {}},
            {
                "id": "n2",
                "type": "guardrail",
                "x": 240,
                "y": 200,
                "config": {"check": "input"},
            },
            {"id": "n3", "type": "llm", "x": 420, "y": 200, "config": {}},
            {
                "id": "n4",
                "type": "guardrail",
                "x": 600,
                "y": 200,
                "config": {"check": "output"},
            },
            {"id": "n5", "type": "output", "x": 780, "y": 200, "config": {}},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4"},
            {"from": "n4", "to": "n5"},
        ],
    },
    {
        "id": "tool-loop",
        "name": "Agentic Tool Loop",
        "description": "LLM decides which tools to use in a loop",
        "nodes": [
            {"id": "n1", "type": "input", "x": 60, "y": 200, "config": {}},
            {"id": "n2", "type": "llm", "x": 260, "y": 200, "config": {}},
            {
                "id": "n3",
                "type": "condition",
                "x": 440,
                "y": 200,
                "config": {"check": "has_tool_calls"},
            },
            {"id": "n4", "type": "tool-dispatch", "x": 440, "y": 60, "config": {}},
            {"id": "n5", "type": "output", "x": 640, "y": 200, "config": {}},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4", "label": "yes"},
            {"from": "n4", "to": "n2"},
            {"from": "n3", "to": "n5", "label": "no"},
        ],
    },
    {
        "id": "chain-of-thought",
        "name": "Chain of Thought",
        "description": "Think step-by-step then summarize",
        "nodes": [
            {"id": "n1", "type": "input", "x": 60, "y": 200, "config": {}},
            {
                "id": "n2",
                "type": "prompt-template",
                "x": 240,
                "y": 200,
                "config": {"template": "Think step by step: {input}"},
            },
            {"id": "n3", "type": "llm", "x": 420, "y": 200, "config": {}},
            {
                "id": "n4",
                "type": "prompt-template",
                "x": 600,
                "y": 200,
                "config": {"template": "Summarize concisely: {input}"},
            },
            {
                "id": "n5",
                "type": "llm",
                "x": 780,
                "y": 200,
                "config": {"label": "Summarizer"},
            },
            {"id": "n6", "type": "output", "x": 960, "y": 200, "config": {}},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4"},
            {"from": "n4", "to": "n5"},
            {"from": "n5", "to": "n6"},
        ],
    },
    {
        "id": "translate-review",
        "name": "Translate & Review",
        "description": "Translate text then have it reviewed for accuracy",
        "nodes": [
            {"id": "n1", "type": "input", "x": 60, "y": 200, "config": {}},
            {
                "id": "n2",
                "type": "prompt-template",
                "x": 240,
                "y": 200,
                "config": {"template": "Translate to English: {input}"},
            },
            {
                "id": "n3",
                "type": "llm",
                "x": 420,
                "y": 200,
                "config": {"label": "Translator"},
            },
            {"id": "n4", "type": "human-review", "x": 600, "y": 200, "config": {}},
            {"id": "n5", "type": "output", "x": 780, "y": 200, "config": {}},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4"},
            {"from": "n4", "to": "n5"},
        ],
    },
    {
        "id": "memory-write-loop",
        "name": "Learn & Remember",
        "description": "Extract knowledge and save to memory wiki",
        "nodes": [
            {"id": "n1", "type": "input", "x": 60, "y": 200, "config": {}},
            {"id": "n2", "type": "llm", "x": 240, "y": 200, "config": {}},
            {"id": "n3", "type": "knowledge-extract", "x": 420, "y": 120, "config": {}},
            {"id": "n4", "type": "memory-write", "x": 600, "y": 120, "config": {}},
            {"id": "n5", "type": "output", "x": 420, "y": 300, "config": {}},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4"},
            {"from": "n2", "to": "n5"},
        ],
    },
    {
        "id": "telegram-auto-reply",
        "name": "Telegram Auto-Reply",
        "description": "Classify incoming Telegram messages and route",
        "nodes": [
            {
                "id": "n1",
                "type": "webhook-trigger",
                "x": 60,
                "y": 200,
                "config": {"platform": "telegram"},
            },
            {
                "id": "n2",
                "type": "classifier",
                "x": 240,
                "y": 200,
                "config": {"categories": ["question", "command", "spam"]},
            },
            {
                "id": "n3",
                "type": "condition",
                "x": 420,
                "y": 200,
                "config": {"check": "category"},
            },
            {
                "id": "n4",
                "type": "llm",
                "x": 600,
                "y": 100,
                "config": {"label": "Answer"},
            },
            {
                "id": "n5",
                "type": "tool-dispatch",
                "x": 600,
                "y": 300,
                "config": {"label": "Execute"},
            },
            {"id": "n6", "type": "output", "x": 780, "y": 200, "config": {}},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4", "label": "question"},
            {"from": "n3", "to": "n5", "label": "command"},
            {"from": "n4", "to": "n6"},
            {"from": "n5", "to": "n6"},
        ],
    },
    {
        "id": "hackernews-daily-telegram",
        "name": "HackerNews Daily Digest",
        "description": "Fetch top HN stories, summarize, send to Telegram",
        "nodes": [
            {"id": "n1", "type": "input", "x": 60, "y": 200, "config": {}},
            {"id": "n2", "type": "hn-fetch", "x": 240, "y": 200, "config": {"count": 10}},
            {"id": "n3", "type": "summarizer", "x": 420, "y": 200, "config": {}},
            {
                "id": "n4",
                "type": "telegram-send",
                "x": 600,
                "y": 200,
                "config": {"chat_id": ""},
            },
            {"id": "n5", "type": "output", "x": 780, "y": 200, "config": {}},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4"},
            {"from": "n4", "to": "n5"},
        ],
    },
]


def load_workflows() -> dict[str, Any]:
    """Load saved workflows + samples."""
    saved: list[dict] = []
    if _WORKFLOWS_PATH.exists():
        try:
            saved = json.loads(_WORKFLOWS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"saved": saved, "samples": _SAMPLES}


def save_workflow(workflow: dict[str, Any]) -> None:
    """Save or update a workflow."""
    saved = load_workflows()["saved"]
    # Update existing or append
    found = False
    for i, w in enumerate(saved):
        if w.get("id") == workflow.get("id"):
            saved[i] = workflow
            found = True
            break
    if not found:
        saved.append(workflow)
    _WORKFLOWS_PATH.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")


def delete_workflow(workflow_id: str) -> bool:
    """Delete a workflow by ID. Returns True if found."""
    saved = load_workflows()["saved"]
    new_saved = [w for w in saved if w.get("id") != workflow_id]
    if len(new_saved) == len(saved):
        return False
    _WORKFLOWS_PATH.write_text(json.dumps(new_saved, indent=2, ensure_ascii=False), encoding="utf-8")
    return True
