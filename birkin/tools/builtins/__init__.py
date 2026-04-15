"""Built-in tool implementations for Birkin agent."""

from __future__ import annotations

from birkin.tools.builtins.file_ops import FileReadTool, FileWriteTool
from birkin.tools.builtins.shell import ShellTool
from birkin.tools.builtins.web_search import WebSearchTool

ALL_BUILTIN_TOOLS = [ShellTool, WebSearchTool, FileReadTool, FileWriteTool]

__all__ = [
    "ALL_BUILTIN_TOOLS",
    "FileReadTool",
    "FileWriteTool",
    "ShellTool",
    "WebSearchTool",
]
