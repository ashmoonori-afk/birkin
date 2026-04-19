"""Code explainer skill — tool implementations."""

from __future__ import annotations

import ast
import re
from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec


class ExplainCodeTool(Tool):
    """Analyze code structure and return a human-readable summary."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="explain_code",
            description=("Analyze code and return a structured summary of its classes, functions, and imports."),
            parameters=[
                ToolParameter(
                    name="code",
                    type="string",
                    description="The source code to explain",
                ),
                ToolParameter(
                    name="language",
                    type="string",
                    description="Programming language of the code",
                    required=False,
                    default="python",
                ),
            ],
            toolset="skills",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        code = args.get("code", "")
        language = args.get("language", "python")

        if not code.strip():
            return ToolOutput(success=False, output="", error="No code provided to explain")

        lines = code.splitlines()
        line_count = len(lines)

        if language.lower() == "python":
            return self._explain_python(code, line_count)

        return self._explain_generic(code, language, line_count)

    @staticmethod
    def _explain_python(code: str, line_count: int) -> ToolOutput:
        """Use the ast module for detailed Python analysis."""
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return ToolOutput(
                success=False,
                output="",
                error=f"Python syntax error: {exc}",
            )

        imports: list[str] = []
        classes: list[str] = []
        functions: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}")
            elif isinstance(node, ast.ClassDef):
                bases = [getattr(b, "id", getattr(b, "attr", "?")) for b in node.bases]
                base_str = f"({', '.join(bases)})" if bases else ""
                classes.append(f"{node.name}{base_str}")
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                arg_names = [a.arg for a in node.args.args]
                functions.append(f"{node.name}({', '.join(arg_names)})")

        parts: list[str] = [f"Python code — {line_count} lines\n"]

        if imports:
            parts.append("Imports:")
            parts.extend(f"  - {imp}" for imp in imports)
            parts.append("")

        if classes:
            parts.append("Classes:")
            parts.extend(f"  - {cls}" for cls in classes)
            parts.append("")

        if functions:
            parts.append("Functions:")
            parts.extend(f"  - {fn}" for fn in functions)
            parts.append("")

        if not (imports or classes or functions):
            parts.append("No classes, functions, or imports detected (script-level code).")

        return ToolOutput(success=True, output="\n".join(parts))

    @staticmethod
    def _explain_generic(code: str, language: str, line_count: int) -> ToolOutput:
        """Use regex heuristics for non-Python languages."""
        pattern = re.compile(r"\b(?:def |function |fn |func )\s*(\w+)")
        matches = pattern.findall(code)

        parts: list[str] = [f"{language} code — {line_count} lines\n"]

        if matches:
            parts.append(f"Functions/methods detected ({len(matches)}):")
            parts.extend(f"  - {name}" for name in matches)
        else:
            parts.append("No function definitions detected via heuristic scan.")

        return ToolOutput(success=True, output="\n".join(parts))
