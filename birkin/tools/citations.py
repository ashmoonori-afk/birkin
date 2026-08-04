"""The ``verify_citations`` tool: check a draft's claims against its sources.

Lives beside the web tools because that is where the sources come from --
``web_fetch`` produces the text this checks against.
"""

from __future__ import annotations

from typing import Any

from . import Tool, ToolContext, ToolResult


def _verify(inp: dict[str, Any], _ctx: ToolContext) -> ToolResult:
    from .. import grounded

    claims = inp.get("claims")
    sources = inp.get("sources")
    if not isinstance(claims, list) or not all(isinstance(c, str) for c in claims):
        return ToolResult("'claims' must be a list of strings.", is_error=True)
    if not isinstance(sources, list):
        return ToolResult(
            "'sources' must be a list of {url, text} objects -- the text you "
            "actually fetched, not a summary of it.", is_error=True)
    return ToolResult(grounded.verify(claims, sources).render())


def tools() -> list[Tool]:
    return [Tool(
        name="verify_citations",
        description=(
            "Check each claim against the source text you fetched, and report "
            "which claims no source actually states. Use before presenting a "
            "cited answer: a claim that comes back UNSUPPORTED must be dropped "
            "or re-sourced, never shipped with the citation attached."),
        input_schema={
            "type": "object",
            "properties": {
                "claims": {"type": "array", "items": {"type": "string"},
                           "description": "One factual statement per entry."},
                "sources": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"url": {"type": "string"},
                                   "text": {"type": "string"}},
                    "required": ["url", "text"]},
                    "description": "Fetched page text, verbatim."},
            },
            "required": ["claims", "sources"]},
        fn=_verify)]
