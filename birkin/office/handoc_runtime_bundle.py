"""Read-only materialized launch bundles for verified HanDoc runtimes."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import final

from . import windows_native
from .handoc_runtime_scan import RuntimeIdentityError, open_runtime_file


def guard_directory(path: Path) -> tuple[int, bool]:
    try:
        if os.name == "nt":
            native = windows_native.api()
            return (
                windows_native.open_handle(
                    path,
                    directory=True,
                    access=native.FILE_READ_ATTRIBUTES,
                    share=native.FILE_SHARE_READ,
                ),
                True,
            )
        return (
            os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            ),
            False,
        )
    except OSError as exc:
        raise RuntimeIdentityError from exc


def freeze_runtime(
    files: list[Path], directories: list[Path], executables: frozenset[Path]
) -> None:
    for path in files:
        os.chmod(path, 0o500 if path in executables else 0o400)
        if hasattr(os, "chflags"):
            os.chflags(path, stat.UF_IMMUTABLE)
    for path in reversed(directories):
        os.chmod(path, 0o500)
        if hasattr(os, "chflags"):
            os.chflags(path, stat.UF_IMMUTABLE)


def thaw_runtime(files: list[Path], directories: list[Path]) -> None:
    for path in [*directories, *files]:
        if hasattr(os, "chflags"):
            try:
                os.chflags(path, 0)
            except OSError:
                pass
        try:
            os.chmod(path, 0o700 if path in directories else 0o600)
        except OSError:
            pass


def close_runtime_guards(guards: list[tuple[int, bool]]) -> None:
    for handle, native in reversed(guards):
        try:
            if native:
                windows_native.close_handle(handle)
            else:
                os.close(handle)
        except OSError:
            pass


@final
class BoundRuntime:
    """Own a verified bundle and its native guards through child completion."""

    def __init__(
        self,
        runner: Path,
        node: Path,
        module_root: Path,
        tools: dict[str, Path],
        files: list[Path],
        directories: list[Path],
        guards: list[tuple[int, bool]],
    ) -> None:
        self.runner = runner
        self.node = node
        self.module_root = module_root
        self._tools = tools
        self._files = files
        self._directories = directories
        self._guards = guards

    def tool(self, name: str) -> Path:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise RuntimeIdentityError from exc

    def __enter__(self) -> BoundRuntime:
        return self

    def __exit__(self, *_error: object) -> None:
        close_runtime_guards(self._guards)
        thaw_runtime(self._files, self._directories)


def bind_bundle(
    runner: Path,
    node: Path,
    module_root: Path,
    tools: dict[str, Path],
    module_files: list[Path],
    destination: Path,
) -> BoundRuntime:
    files = [runner, node, *module_files]
    directories = [
        path
        for path in [destination, module_root, *module_root.rglob("*")]
        if path.is_dir()
    ]
    try:
        freeze_runtime(files, directories, frozenset({runner, node}))
    except OSError:
        thaw_runtime(files, directories)
        raise
    guards: list[tuple[int, bool]] = []
    try:
        guards.extend((open_runtime_file(path), False) for path in files)
        guards.extend(guard_directory(path) for path in directories)
    except (OSError, RuntimeIdentityError):
        close_runtime_guards(guards)
        thaw_runtime(files, directories)
        raise
    return BoundRuntime(runner, node, module_root, tools, files, directories, guards)
