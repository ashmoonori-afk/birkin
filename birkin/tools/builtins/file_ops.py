"""File read/write tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec

_MAX_READ_CHARS = 10_000


def _resolve_safe_path(raw_path: str, working_dir: str | None) -> tuple[Path, str | None]:
    """Resolve the path and check it stays within the working directory.

    Returns (resolved_path, error_message). error_message is None when safe.
    """
    target = Path(raw_path).expanduser()

    if working_dir:
        base = Path(working_dir).resolve()
        # Resolve relative paths against working_dir.
        if not target.is_absolute():
            target = base / target
        resolved = target.resolve()

        # Security: ensure the resolved path is under the working directory.
        try:
            resolved.relative_to(base)
        except ValueError:
            return resolved, f"Path '{raw_path}' resolves outside the working directory."
    else:
        resolved = target.resolve()

    return resolved, None


class FileReadTool(Tool):
    """Read the contents of a file."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="file_read",
            description=(
                "Read a file and return its contents. Output is truncated to 10 000 characters for large files."
            ),
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Path to the file to read.",
                    required=True,
                ),
            ],
            toolset="builtin",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        raw_path = args.get("path", "").strip()
        if not raw_path:
            return ToolOutput(success=False, output="", error="No file path provided.")

        resolved, err = _resolve_safe_path(raw_path, context.working_dir if context else None)
        if err:
            return ToolOutput(success=False, output="", error=err)

        if not resolved.exists():
            return ToolOutput(success=False, output="", error=f"File not found: {resolved}")

        if not resolved.is_file():
            return ToolOutput(success=False, output="", error=f"Not a file: {resolved}")

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolOutput(success=False, output="", error=f"Failed to read file: {exc}")

        truncated = len(content) > _MAX_READ_CHARS
        if truncated:
            content = content[:_MAX_READ_CHARS] + "\n... [truncated]"

        return ToolOutput(
            success=True,
            output=content,
            metadata={"path": str(resolved), "truncated": truncated},
        )


class FileWriteTool(Tool):
    """Write content to a file."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="file_write",
            description=(
                "Write content to a file. Creates the file (and parent directories) "
                "if they do not exist. The path must stay within the working directory."
            ),
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Path to the file to write.",
                    required=True,
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="Content to write to the file.",
                    required=True,
                ),
            ],
            toolset="builtin",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        raw_path = args.get("path", "").strip()
        content = args.get("content", "")

        if not raw_path:
            return ToolOutput(success=False, output="", error="No file path provided.")

        working_dir = context.working_dir if context else None
        if not working_dir:
            return ToolOutput(
                success=False,
                output="",
                error="Cannot write files without a working directory set in context.",
            )

        resolved, err = _resolve_safe_path(raw_path, working_dir)
        if err:
            return ToolOutput(success=False, output="", error=err)

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolOutput(success=False, output="", error=f"Failed to write file: {exc}")

        return ToolOutput(
            success=True,
            output=f"Wrote {len(content)} characters to {resolved}",
            metadata={"path": str(resolved), "chars_written": len(content)},
        )
