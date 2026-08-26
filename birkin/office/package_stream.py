"""Descriptor-stable streaming reads for validated Office packages."""

from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from . import package_types as types
from .errors import DocumentError
from .limits import PackageLimits as BasePackageLimits
from .package_scan import (
    _normalize,
    _read_verified,
    _scan_archive,
    package_invalid,
)
from .package_types import DEFAULT_LIMITS, PackageLimits
from .package_xml import XMLPackageBudget


class PackagePayloads(Mapping[str, bytes]):
    """Read one previously scanned archive payload at a time."""

    def __init__(
        self,
        archive: zipfile.ZipFile,
        parts: dict[str, types.ScannedPartManifest],
    ) -> None:
        self._archive = archive
        self._parts = parts

    def __getitem__(self, name: str) -> bytes:
        metadata = self._parts[name]
        info = self._archive.infolist()[metadata["index"]]
        content = _read_verified(self._archive, info)
        if hashlib.sha256(content).hexdigest() != metadata["original_sha256"]:
            raise package_invalid(
                f"package entry changed after preflight: {name}",
                reason="zip_integrity",
            )
        return content

    def __iter__(self) -> Iterator[str]:
        return iter(self._parts)

    def __len__(self) -> int:
        return len(self._parts)


@contextmanager
def stream_package_payloads(
    path: Path,
    limits: BasePackageLimits = DEFAULT_LIMITS,
) -> Iterator[Mapping[str, bytes]]:
    """Validate an archive and expose descriptor-stable payload reads."""
    try:
        legacy = not isinstance(limits, PackageLimits)
        effective = _normalize(limits)
        with zipfile.ZipFile(path) as archive:
            scan = _scan_archive(
                archive,
                effective,
                [0],
                0,
                legacy,
                XMLPackageBudget(),
            )
            yield PackagePayloads(archive, scan["parts"])
    except DocumentError:
        raise
    except (OSError, EOFError, zipfile.BadZipFile, RuntimeError) as exc:
        raise package_invalid(str(exc), reason="zip_integrity") from exc
