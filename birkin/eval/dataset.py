"""Evaluation dataset — models for eval cases and datasets."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field


class EvalCase(BaseModel):
    """A single evaluation case."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    input: dict[str, Any] = {}
    expected_output: Optional[str] = None
    rubric: list[str] = []
    tags: list[str] = []


class EvalDataset(BaseModel):
    """A collection of evaluation cases."""

    name: str
    cases: list[EvalCase] = []

    @classmethod
    def from_jsonl(cls, path: Path, name: Optional[str] = None) -> EvalDataset:
        """Load a dataset from a JSONL file."""
        cases: list[EvalCase] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            cases.append(EvalCase(**data))
        return cls(name=name or path.stem, cases=cases)

    def to_jsonl(self, path: Path) -> None:
        """Save the dataset to a JSONL file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [case.model_dump_json() for case in self.cases]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
