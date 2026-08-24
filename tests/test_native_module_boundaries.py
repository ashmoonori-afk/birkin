"""Structural boundaries for native and owned-terminal integration modules."""

from __future__ import annotations

from pathlib import Path

_MAX_PURE_LOC = 250
_MODULE_PATTERNS = (
    "native/private_storage*.py",
    "native/protocol*.py",
    "native/serve*.py",
    "native/server*.py",
    "native/transport*.py",
    "workspace/owned_terminal*.py",
)


def _pure_loc(path: Path) -> int:
    return sum(
        bool(line.strip()) and not line.lstrip().startswith("#")
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def test_native_and_owned_terminal_modules_obey_small_module_gate() -> None:
    # Given
    package_root = Path(__file__).parents[1] / "birkin"
    modules = {
        module
        for pattern in _MODULE_PATTERNS
        for module in package_root.glob(pattern)
    }

    # When
    oversized = {
        str(module.relative_to(package_root)): _pure_loc(module)
        for module in sorted(modules)
        if _pure_loc(module) > _MAX_PURE_LOC
    }

    # Then
    assert oversized == {}
