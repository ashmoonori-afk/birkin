"""Regression proofs that removed external Office engines stay unreachable."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

REMOVED_MODULES = (
    "birkin.office.handoc_child_process",
    "birkin.office.handoc_execution",
    "birkin.office.handoc_identity",
    "birkin.office.handoc_process",
    "birkin.office.handoc_runtime_bundle",
    "birkin.office.handoc_runtime_scan",
)


def test_external_hwpx_engine_modules_are_not_shipped() -> None:
    assert all(
        importlib.util.find_spec(module_name) is None
        for module_name in REMOVED_MODULES
    )


def test_office_python_never_imports_a_process_factory() -> None:
    violations: list[str] = []
    for path in sorted(Path("birkin/office").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name == "subprocess" for alias in node.names
            ):
                violations.append(f"{path}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
                violations.append(f"{path}:{node.lineno}")
    assert violations == []
