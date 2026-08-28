"""Descriptor-relative generic file-tool directory listing."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from .file_target import (
    PathPolicy,
    UnsafeTargetError,
    descriptor_final_path,
)


def render_tree(
    base: Path,
    *,
    depth: int,
    policy: PathPolicy,
) -> str:
    if os.name == "nt":
        return _render_windows(base, depth=depth, policy=policy)
    canonical = Path(os.path.realpath(base))
    descriptor = _open_directory(canonical)
    try:
        final = descriptor_final_path(descriptor)
        _authorize(final, policy)
        lines = [f"{base}/"]
        _walk(
            descriptor,
            final,
            level=1,
            depth=depth,
            prefix="  ",
            policy=policy,
            lines=lines,
        )
        return "\n".join(lines)
    finally:
        os.close(descriptor)


def _walk(
    descriptor: int,
    path: Path,
    *,
    level: int,
    depth: int,
    prefix: str,
    policy: PathPolicy,
    lines: list[str],
) -> None:
    if level > depth:
        return
    for name in sorted(os.listdir(descriptor), key=str.lower):
        if name.startswith(".") and name != ".birkin":
            continue
        metadata = os.stat(
            name,
            dir_fd=descriptor,
            follow_symlinks=False,
        )
        is_directory = stat.S_ISDIR(metadata.st_mode)
        lines.append(f"{prefix}{name}{'/' if is_directory else ''}")
        if not is_directory:
            continue
        child = os.open(
            name,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=descriptor,
        )
        try:
            final = descriptor_final_path(child)
            _authorize(final, policy)
            _walk(
                child,
                path / name,
                level=level + 1,
                depth=depth,
                prefix=prefix + "  ",
                policy=policy,
                lines=lines,
            )
        finally:
            os.close(child)


def _open_directory(path: Path) -> int:
    return os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )


def _authorize(path: Path, policy: PathPolicy) -> None:
    blocked = policy(path)
    if blocked:
        raise UnsafeTargetError(1, blocked, path)


def _render_windows(
    base: Path,
    *,
    depth: int,
    policy: PathPolicy,
) -> str:
    canonical = Path(os.path.realpath(base))
    lines = [f"{base}/"]
    _walk_windows(
        canonical,
        level=1,
        depth=depth,
        prefix="  ",
        policy=policy,
        lines=lines,
    )
    return "\n".join(lines)


def _walk_windows(
    path: Path,
    *,
    level: int,
    depth: int,
    prefix: str,
    policy: PathPolicy,
    lines: list[str],
) -> None:
    from .file_target_windows import (
        close_handle,
        handle_final_path,
        open_directory,
    )

    handle = open_directory(path)
    try:
        final = handle_final_path(handle)
        _authorize(final, policy)
        if level > depth:
            return
        with os.scandir(final) as entries:
            ordered = sorted(entries, key=lambda entry: entry.name.lower())
        for entry in ordered:
            if entry.name.startswith(".") and entry.name != ".birkin":
                continue
            is_directory = entry.is_dir(follow_symlinks=False)
            lines.append(
                f"{prefix}{entry.name}{'/' if is_directory else ''}"
            )
            if is_directory:
                _walk_windows(
                    final / entry.name,
                    level=level + 1,
                    depth=depth,
                    prefix=prefix + "  ",
                    policy=policy,
                    lines=lines,
                )
    finally:
        close_handle(handle)
