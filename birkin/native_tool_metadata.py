"""Canonical names and scheduling posture for Birkin-authored tools.

This module intentionally has no Birkin imports. Registry collision handling,
effect resolution, and the legacy parallel planner can all depend on it without
creating an import cycle.
"""

from __future__ import annotations

from types import MappingProxyType

# Every Birkin-authored runtime tool appears exactly once. ``True`` means the
# tool is inspect-only and safe to run concurrently with adjacent safe calls.
NATIVE_TOOL_METADATA = MappingProxyType(
    {
        "read_file": True,
        "edit_file": False,
        "write_file": False,
        "list_files": True,
        "run_shell": False,
        "web_fetch": True,
        "web_search": False,
        "market_quote": False,
        "verify_citations": False,
        "session_search": True,
        "session_get": True,
        "vision_analyze": False,
        "browser_navigate": False,
        "browser_click": False,
        "browser_fill": False,
        "browser_press": False,
        "browser_execute": False,
        "browser_screenshot": False,
        "browser_evidence": False,
        "browser_close": False,
        "submit_payload": False,
        "list_document_adapters": False,
        "inspect_document": False,
        "extract_document": False,
        "compare_documents": False,
        "render_artifact": False,
        "validate_artifact": False,
        "office_job_request": False,
        "worker_invoke": False,
        "spawn_subagent": False,
        "desktop_windows": False,
        "window_screenshot": False,
        "computer_use": False,
        "companion_propose": False,
        "load_skill": False,
        "create_skill": False,
        "improve_skill": False,
        "remember": False,
        "memory_write_note": False,
        "memory_search": True,
        "memory_get_note": True,
        "memory_link": False,
        "memory_related": True,
        "memory_rezone": False,
        "profile_write": False,
    }
)

NATIVE_TOOL_NAMES = frozenset(NATIVE_TOOL_METADATA)
NATIVE_INSPECT_PARALLEL_TOOLS = frozenset(
    name for name, parallel_safe in NATIVE_TOOL_METADATA.items() if parallel_safe
)
