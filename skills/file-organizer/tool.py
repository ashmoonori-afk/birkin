"""File organizer skill — tool implementations."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec


class OrganizeFilesTool(Tool):
    """Produce a dry-run plan for organizing files in a directory."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="organize_files",
            description=(
                "Scan a directory and produce a dry-run plan for organizing "
                "files by extension. Does NOT move any files."
            ),
            parameters=[
                ToolParameter(
                    name="directory",
                    type="string",
                    description="Absolute path to the directory to organize",
                ),
                ToolParameter(
                    name="strategy",
                    type="string",
                    description="Organization strategy (currently: extension)",
                    required=False,
                    default="extension",
                ),
            ],
            toolset="skills",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        directory = args.get("directory", "")
        strategy = args.get("strategy", "extension")

        if not directory.strip():
            return ToolOutput(success=False, output="", error="Directory path is required")

        dir_path = Path(directory)

        if not dir_path.exists():
            return ToolOutput(
                success=False,
                output="",
                error=f"Directory not found: {directory}",
            )

        if not dir_path.is_dir():
            return ToolOutput(
                success=False,
                output="",
                error=f"Path is not a directory: {directory}",
            )

        if strategy != "extension":
            return ToolOutput(
                success=False,
                output="",
                error=f"Unsupported strategy: '{strategy}'. Currently only 'extension' is supported.",
            )

        return self._plan_by_extension(dir_path)

    @staticmethod
    def _plan_by_extension(dir_path: Path) -> ToolOutput:
        """Group files by extension and build a move plan."""
        groups: dict[str, list[str]] = defaultdict(list)

        for item in dir_path.iterdir():
            if item.is_file():
                ext = item.suffix.lstrip(".").lower() if item.suffix else "no-extension"
                groups[ext].append(item.name)

        if not groups:
            return ToolOutput(success=True, output="No files found in directory.")

        plan_lines: list[str] = [
            f"Dry-run plan for: {dir_path}",
            "Strategy: extension",
            f"Files found: {sum(len(v) for v in groups.values())}",
            "",
        ]

        for ext in sorted(groups):
            folder = ext
            plan_lines.append(f"[{folder}/] ({len(groups[ext])} files)")
            for fname in sorted(groups[ext]):
                plan_lines.append(f"  Would move {fname} -> {folder}/{fname}")
            plan_lines.append("")

        plan_lines.append("NOTE: This is a dry-run. No files were moved.")

        return ToolOutput(success=True, output="\n".join(plan_lines))
