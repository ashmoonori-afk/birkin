from __future__ import annotations

import ast
from pathlib import Path


def test_existing_python_authority_never_imports_native_layer() -> None:
    package_root = Path(__file__).resolve().parents[1] / "birkin"
    violations: list[str] = []

    for path in package_root.rglob("*.py"):
        if "native" in path.relative_to(package_root).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module: str | None = None
            line_number = 0
            if isinstance(node, ast.ImportFrom):
                module = node.module
                line_number = node.lineno
            elif isinstance(node, ast.Import):
                line_number = node.lineno
                module = next(
                    (
                        alias.name
                        for alias in node.names
                        if alias.name.startswith("birkin.native")
                    ),
                    None,
                )
            if module is not None and module.startswith("birkin.native"):
                violations.append(
                    f"{path.relative_to(package_root)}:{line_number}"
                )

    assert violations == []
