"""Immutable in-memory imports for verified plugin snapshot bytes."""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import weakref
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from importlib.abc import MetaPathFinder, SourceLoader
from importlib.machinery import ModuleSpec
from pathlib import Path, PurePosixPath
from types import ModuleType, TracebackType
from typing import BinaryIO, Literal, Protocol


class SnapshotImportError(ImportError):
    """A captured plugin module cannot be represented safely."""


class SnapshotActivationError(RuntimeError):
    """Marker for an already typed plugin activation failure."""


class SnapshotTransactionError(RuntimeError):
    """A plugin activation transaction failed after snapshot creation."""


class CleanupOwner(Protocol):
    def cleanup(self) -> None: ...


class _MemoryResources:
    def __init__(
        self,
        files: Mapping[str, bytes],
        package: PurePosixPath,
    ) -> None:
        self._files = files
        self._package = package
        self._buffer = io.BytesIO()
        self._archive = zipfile.ZipFile(self._buffer, "w")
        directories = {
            parent.as_posix()
            for name in files
            for parent in PurePosixPath(name).parents
            if parent.as_posix() != "."
        }
        for directory in sorted(directories):
            self._archive.writestr(f"{directory}/", b"")
        for name, data in files.items():
            self._archive.writestr(name, data)

    def open_resource(
        self,
        resource: str | os.PathLike[str],
    ) -> BinaryIO:
        relative = (self._package / os.fspath(resource)).as_posix()
        try:
            return io.BytesIO(self._files[relative])
        except KeyError as exc:
            raise FileNotFoundError(relative) from exc

    def resource_path(
        self,
        resource: str | os.PathLike[str],
    ) -> str:
        raise FileNotFoundError(os.fspath(resource))

    def is_resource(
        self,
        path: str | os.PathLike[str],
    ) -> bool:
        relative = (self._package / os.fspath(path)).as_posix()
        return relative in self._files

    def contents(self) -> Iterator[str]:
        prefix = f"{self._package.as_posix().rstrip('/')}/"
        children = {
            name[len(prefix):].partition("/")[0]
            for name in self._files
            if name.startswith(prefix)
        }
        return iter(sorted(children))

    def files(self) -> zipfile.Path:
        return zipfile.Path(
            self._archive,
            at=f"{self._package.as_posix().rstrip('/')}/",
        )


class SnapshotLoader(SourceLoader, MetaPathFinder):
    """Load one captured entry package and its children without path reopens."""

    def __init__(
        self,
        module_name: str,
        root: Path,
        entry: PurePosixPath,
        files: Mapping[str, bytes],
    ) -> None:
        self._module_name = module_name
        self._root = root
        self._entry = entry
        self._files = files
        self._entry_is_package = entry.name == "__init__.py"
        self._package_root = entry.parent

    def _record(
        self,
        fullname: str,
    ) -> tuple[PurePosixPath, bool] | None:
        if fullname == self._module_name:
            return self._entry, self._entry_is_package
        prefix = f"{self._module_name}."
        if not self._entry_is_package or not fullname.startswith(prefix):
            return None
        relative = fullname[len(prefix):].split(".")
        package = self._package_root.joinpath(*relative, "__init__.py")
        if package.as_posix() in self._files:
            return package, True
        module = self._package_root.joinpath(*relative[:-1], f"{relative[-1]}.py")
        if module.as_posix() in self._files:
            return module, False
        return None

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        del path, target
        record = self._record(fullname)
        if record is None:
            return None
        relative, is_package = record
        spec = importlib.util.spec_from_loader(
            fullname,
            self,
            origin=str(self._root / relative),
            is_package=is_package,
        )
        if spec is not None:
            spec.has_location = True
        return spec

    def get_filename(self, fullname: str) -> str:
        record = self._record(fullname)
        if record is None:
            raise SnapshotImportError(f"unknown captured plugin module: {fullname}")
        return str(self._root / record[0])

    def get_data(self, path: str) -> bytes:
        try:
            relative = Path(path).relative_to(self._root).as_posix()
            return self._files[relative]
        except (KeyError, ValueError) as exc:
            raise OSError(f"captured plugin path is unavailable: {path}") from exc

    def is_package(self, fullname: str) -> bool:
        record = self._record(fullname)
        if record is None:
            raise SnapshotImportError(f"unknown captured plugin module: {fullname}")
        return record[1]

    def get_resource_reader(
        self,
        fullname: str,
    ) -> _MemoryResources | None:
        record = self._record(fullname)
        if record is None or not record[1]:
            return None
        return _MemoryResources(self._files, record[0].parent)

    def module_spec(self) -> ModuleSpec:
        spec = self.find_spec(self._module_name, None)
        if spec is None:
            raise SnapshotImportError(
                f"cannot represent captured plugin module: {self._module_name}"
            )
        return spec


def _release_loader(
    loaders: list[SnapshotLoader],
    owner: CleanupOwner,
) -> None:
    for loader in loaders:
        if loader in sys.meta_path:
            sys.meta_path.remove(loader)
    owner.cleanup()


class SnapshotLifetime:
    """Keep captured imports and their origin directory alive with the module."""

    def __init__(
        self,
        owner: CleanupOwner,
    ) -> None:
        self._loaders: list[SnapshotLoader] = []
        self._finalizer = weakref.finalize(
            self,
            _release_loader,
            self._loaders,
            owner,
        )

    def add_loader(self, loader: SnapshotLoader) -> None:
        self._loaders.append(loader)

    def rollback(self) -> None:
        loaders = set(self._loaders)
        for name, module in tuple(sys.modules.items()):
            if module.__loader__ in loaders:
                sys.modules.pop(name, None)
        self._finalizer()


class SnapshotActivation:
    """Own every snapshot lifetime created by one activation call."""

    def __init__(self) -> None:
        self._lifetimes: list[SnapshotLifetime] = []

    def __enter__(self) -> SnapshotActivation:
        return self

    def add_owner(self, owner: CleanupOwner) -> SnapshotLifetime:
        lifetime = SnapshotLifetime(owner)
        self._lifetimes.append(lifetime)
        return lifetime

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del exception_type, traceback
        if exception is None:
            return False
        for lifetime in reversed(self._lifetimes):
            lifetime.rollback()
        if isinstance(exception, SnapshotActivationError):
            return False
        if isinstance(exception, Exception):
            raise SnapshotTransactionError(
                "plugin activation transaction failed"
            ) from exception
        return False


def load_snapshot_module(
    module_name: str,
    root: Path,
    entry: PurePosixPath,
    files: Mapping[str, bytes],
    lifetime: SnapshotLifetime,
) -> ModuleType:
    """Execute a captured entry module through its immutable byte mapping."""
    loader = SnapshotLoader(module_name, root, entry, files)
    spec = loader.module_spec()
    module = importlib.util.module_from_spec(spec)
    lifetime.add_loader(loader)
    module.__dict__["__birkin_plugin_snapshot__"] = lifetime
    sys.meta_path.insert(0, loader)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module
