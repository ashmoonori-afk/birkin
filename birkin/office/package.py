"""Public Office package inventory and surgical clone API."""

from pathlib import Path
from typing import cast

from .artifact_snapshot import SnapshotPath
from .limits import PackageLimits as BasePackageLimits
from .package_clone import clone_package
from .package_scan import preflight_package as _preflight_package
from .package_types import (
    DEFAULT_LIMITS,
    ActiveContent,
    ExternalRelationship,
    PackageLimits,
    PackageManifest,
    PartManifest,
)


def preflight_package(
    path: Path | SnapshotPath,
    limits: BasePackageLimits = DEFAULT_LIMITS,
) -> PackageManifest:
    """Scan a path and retain descriptor-bound identity when one is supplied."""
    manifest = _preflight_package(cast(Path, cast(object, path)), limits)
    if isinstance(path, SnapshotPath):
        manifest["source_sha256"] = path.sha256()
    return manifest


__all__ = [
    "ActiveContent",
    "ExternalRelationship",
    "PackageLimits",
    "PackageManifest",
    "PartManifest",
    "clone_package",
    "preflight_package",
]
