"""Identity scanning and guarded launch bundles for HanDoc runtimes."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .handoc_runtime_bundle import BoundRuntime, bind_bundle
from .handoc_runtime_scan import RuntimeIdentityError, copy_pinned, scan_modules


def runtime_is_valid(
    config: Mapping[str, object], required_packages: Mapping[str, str]
) -> bool:
    try:
        _ = copy_pinned(config, "isolation_runner_path", "isolation_runner_sha256", None)
        _ = copy_pinned(config, "node_path", "node_sha256", None)
        _ = scan_modules(config, None, required_packages)
        return True
    except RuntimeIdentityError:
        return False


def bind_runtime(
    config: Mapping[str, object],
    destination: Path,
    required_packages: Mapping[str, str],
) -> BoundRuntime:
    try:
        destination.mkdir(mode=0o700)
        runner = copy_pinned(
            config, "isolation_runner_path", "isolation_runner_sha256", destination
        )
        node = copy_pinned(config, "node_path", "node_sha256", destination)
        module_root, tools, module_files = scan_modules(
            config, destination, required_packages
        )
        return bind_bundle(
            runner, node, module_root, tools, module_files, destination
        )
    except (OSError, RuntimeIdentityError) as exc:
        raise RuntimeIdentityError from exc
