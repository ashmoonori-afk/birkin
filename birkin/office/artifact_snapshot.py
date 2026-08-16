"""Identity-bound artifact snapshot handles for service consumers."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import BinaryIO, TextIO, cast, final

from typing_extensions import override

from . import artifact_snapshot_platform as _snapshot_platform
from .artifact_identity import verify_descriptor_identity
from .errors import DocumentError, DocumentErrorCode
from .path_security import hash_descriptor, open_regular

RegisterSnapshot = Callable[[str, "ArtifactSnapshot"], None]
UnregisterSnapshot = Callable[[str, "ArtifactSnapshot"], None]
SnapshotProtector = Callable[[Path, int], None]


def protect_snapshot(
    path: Path,
    descriptor: int,
    *,
    platform: str | None = None,
) -> None:
    """Make a completed snapshot read-only with native-safe primitives."""
    _snapshot_platform.protect_snapshot(path, descriptor, platform=platform)


def sync_read_descriptor(descriptor: int, *, platform: str | None = None) -> None:
    """Flush read descriptors where the platform supports that operation."""
    _snapshot_platform.sync_read_descriptor(descriptor, platform=platform)


def snapshot_from_descriptor(
    logical_path: Path,
    source_descriptor: int,
    digest: str,
    home: Path,
    configured_home: Path,
    register: RegisterSnapshot,
    unregister: UnregisterSnapshot,
    protect: SnapshotProtector = protect_snapshot,
) -> ArtifactSnapshot:
    """Copy from a verified descriptor and bind the copy for its whole lifetime."""
    snapshot_fd, name = tempfile.mkstemp(
        prefix=".birkin-read-", suffix=logical_path.suffix, dir=home
    )
    snapshot = Path(name)
    bound_fd = -1
    storage: Path | None = snapshot
    try:
        with os.fdopen(os.dup(source_descriptor), "rb") as incoming, os.fdopen(
            os.dup(snapshot_fd), "wb"
        ) as outgoing:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        protect(snapshot, snapshot_fd)
        if os.name == "nt":
            writable_fd, snapshot_fd = snapshot_fd, -1
            bound_fd = _snapshot_platform.replace_with_windows_snapshot_guard(
                writable_fd, snapshot
            )
        else:
            bound_fd = open_regular(snapshot, home, configured_home)
            os.close(snapshot_fd)
            snapshot_fd = -1
        if os.name == "posix":
            _snapshot_platform.prepare_snapshot_cleanup(snapshot)
            snapshot.unlink()
            storage = None
            if os.fstat(bound_fd).st_nlink != 0:
                raise DocumentError(
                    DocumentErrorCode.SOURCE_CHANGED,
                    "import",
                    "artifact snapshot retained an unexpected link",
                )
        if hash_descriptor(bound_fd) != digest:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "import",
                "verified artifact snapshot hash changed",
                artifact_sha256=digest,
            )
        _ = verify_descriptor_identity(bound_fd, logical_path)
        result = ArtifactSnapshot(
            logical_path, storage, bound_fd, digest, register, unregister
        )
        bound_fd = -1
        return result
    except BaseException:
        if snapshot_fd >= 0:
            os.close(snapshot_fd)
        if bound_fd >= 0:
            os.close(bound_fd)
        if storage is not None:
            _snapshot_platform.prepare_snapshot_cleanup(storage)
            storage.unlink(missing_ok=True)
        raise
    finally:
        os.close(source_descriptor)


@final
class SnapshotPath(os.PathLike[str]):
    """Path-compatible read view whose system path is a held descriptor."""

    def __init__(
        self,
        access_path: Path,
        logical_path: Path,
        descriptor: int,
    ) -> None:
        self._access_path = access_path
        self._logical_path = logical_path
        self._descriptor = descriptor

    @override
    def __fspath__(self) -> str:
        _ = os.lseek(self._descriptor, 0, os.SEEK_SET)
        return str(self._access_path)

    @override
    def __str__(self) -> str:
        return self.__fspath__()

    @property
    def name(self) -> str:
        return self._logical_path.name

    @property
    def suffix(self) -> str:
        return self._logical_path.suffix

    def open(
        self,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> BinaryIO | TextIO:
        return cast(
            "BinaryIO | TextIO",
            open(self, mode, buffering, encoding, errors, newline),
        )

    def read_bytes(self) -> bytes:
        with self.open("rb") as source:
            return cast(bytes, source.read())

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
        return os.stat(self, follow_symlinks=follow_symlinks)

    def resolve(self, strict: bool = False) -> SnapshotPath:
        _ = strict
        return self

    def is_relative_to(self, other: Path) -> bool:
        return self._logical_path.is_relative_to(other)

    def sha256(self) -> str:
        return hash_descriptor(self._descriptor)


@final
class ArtifactSnapshot:
    """Own one immutable descriptor and register it for nested service calls."""

    def __init__(
        self,
        logical_path: Path,
        storage_path: Path | None,
        descriptor: int,
        digest: str,
        register: RegisterSnapshot,
        unregister: UnregisterSnapshot,
    ) -> None:
        access_path = (
            storage_path
            if storage_path is not None
            else _snapshot_platform.descriptor_snapshot_path(descriptor)
        )
        self.logical_path = logical_path
        self.storage_path = storage_path
        self.descriptor = descriptor
        self.digest = digest
        self.path = SnapshotPath(access_path, logical_path, descriptor)
        self._register = register
        self._unregister = unregister
        self._entered = False

    @property
    def key(self) -> str:
        return os.fspath(self.path)

    def verify(self, expected: object | None = None) -> None:
        if expected is not None and expected != self.digest:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "import",
                "artifact hash mismatch",
                artifact_sha256=self.digest,
            )
        if hash_descriptor(self.descriptor) != self.digest:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "import",
                "verified artifact snapshot changed",
                artifact_sha256=self.digest,
            )
        _ = verify_descriptor_identity(self.descriptor, self.logical_path)

    def duplicate(self, expected: object) -> tuple[Path, int, str]:
        self.verify(expected)
        return self.logical_path, os.dup(self.descriptor), self.digest

    def __enter__(self) -> Path:
        self.verify()
        self._register(self.key, self)
        self._entered = True
        return cast(Path, cast(object, self.path))

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        failure: DocumentError | None = None
        if self._entered:
            self._unregister(self.key, self)
        try:
            self.verify()
        except DocumentError as exc:
            if exc_type is None:
                failure = exc
        if self.storage_path is not None:
            _snapshot_platform.prepare_snapshot_cleanup(self.storage_path)
        os.close(self.descriptor)
        if self.storage_path is not None:
            self.storage_path.unlink(missing_ok=True)
        if failure is not None:
            raise failure
