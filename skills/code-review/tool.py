"""Code review skill — tool implementations."""

from __future__ import annotations

from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec


class ReviewCodeTool(Tool):
    """Analyze code for quality, security, and best practice issues."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="review_code",
            description="Review code for quality, security, and best practice issues. Returns structured feedback.",
            parameters=[
                ToolParameter(
                    name="code",
                    type="string",
                    description="The code to review",
                ),
                ToolParameter(
                    name="language",
                    type="string",
                    description="Programming language (e.g. python, javascript, go)",
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
            return ToolOutput(success=False, output="", error="No code provided to review")

        # Static analysis heuristics (lightweight, no LLM needed)
        issues: list[str] = []
        lines = code.splitlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Security checks
            if (
                any(kw in stripped.lower() for kw in ("password=", "secret=", "api_key="))
                and "os.environ" not in stripped
                and "getenv" not in stripped
            ):
                issues.append(f"[CRITICAL] Line {i}: Possible hardcoded secret")

            if "eval(" in stripped or "exec(" in stripped:
                issues.append(f"[HIGH] Line {i}: Use of eval/exec — potential code injection")

            if "# TODO" in stripped or "# FIXME" in stripped:
                issues.append(f"[LOW] Line {i}: Unresolved TODO/FIXME")

            # Quality checks
            if len(line) > 120:
                issues.append(f"[LOW] Line {i}: Line exceeds 120 characters ({len(line)})")

            if stripped.startswith("except:") or stripped == "except Exception:":
                issues.append(f"[MEDIUM] Line {i}: Bare except clause — catch specific exceptions")

            if stripped.startswith("print("):
                issues.append(f"[LOW] Line {i}: print() statement — use logging module instead")

        if not issues:
            summary = f"No issues found in {len(lines)} lines of {language} code."
        else:
            summary = f"Found {len(issues)} issue(s) in {len(lines)} lines of {language} code:\n\n"
            summary += "\n".join(f"- {issue}" for issue in issues)

        return ToolOutput(success=True, output=summary)
