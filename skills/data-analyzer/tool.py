"""Data analyzer skill — tool implementations."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from birkin.tools.base import Tool, ToolContext, ToolOutput, ToolParameter, ToolSpec


class AnalyzeDataTool(Tool):
    """Analyze CSV or JSON data and return summary statistics."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="analyze_data",
            description=(
                "Analyze structured data (CSV or JSON) and return summary "
                "statistics including row count, column names, types, and "
                "numeric aggregates."
            ),
            parameters=[
                ToolParameter(
                    name="data",
                    type="string",
                    description="Data as a CSV or JSON string",
                ),
            ],
            toolset="skills",
        )

    async def execute(self, args: dict[str, Any], context: ToolContext) -> ToolOutput:
        data = args.get("data", "")

        if not data.strip():
            return ToolOutput(success=False, output="", error="No data provided to analyze")

        rows = self._parse_data(data)
        if rows is None:
            return ToolOutput(
                success=False,
                output="",
                error="Unable to parse data as JSON or CSV",
            )

        if not rows:
            return ToolOutput(success=True, output="Dataset is empty (0 rows).")

        columns = list(rows[0].keys())
        row_count = len(rows)

        col_stats: list[str] = []
        for col in columns:
            values = [row.get(col) for row in rows]
            numeric = self._to_numeric(values)

            if numeric:
                col_min = min(numeric)
                col_max = max(numeric)
                col_mean = sum(numeric) / len(numeric)
                col_stats.append(
                    f"  {col}: numeric — "
                    f"min={col_min:.4g}, max={col_max:.4g}, mean={col_mean:.4g} "
                    f"({len(numeric)}/{row_count} numeric values)"
                )
            else:
                sample = [str(v) for v in values[:3] if v is not None]
                col_stats.append(f"  {col}: text — sample: {sample}")

        parts = [
            f"Rows: {row_count}",
            f"Columns ({len(columns)}): {', '.join(columns)}",
            "",
            "Column details:",
            *col_stats,
        ]

        return ToolOutput(success=True, output="\n".join(parts))

    @staticmethod
    def _parse_data(data: str) -> list[dict[str, Any]] | None:
        """Try JSON first, then CSV."""
        # JSON
        try:
            parsed = json.loads(data)
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

        # CSV
        try:
            reader = csv.DictReader(io.StringIO(data))
            rows = list(reader)
            if rows and rows[0]:
                return rows
        except csv.Error:
            pass

        return None

    @staticmethod
    def _to_numeric(values: list[Any]) -> list[float]:
        """Extract numeric values from a list, skipping non-numeric."""
        result: list[float] = []
        for v in values:
            if v is None:
                continue
            try:
                result.append(float(v))
            except (ValueError, TypeError):
                continue
        return result
