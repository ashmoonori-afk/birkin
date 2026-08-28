"""Exact byte copy between already opened export descriptors."""

from __future__ import annotations

import os


def copy_descriptor(source: int, target: int) -> None:
    _ = os.lseek(source, 0, os.SEEK_SET)
    _ = os.lseek(target, 0, os.SEEK_SET)
    while chunk := os.read(source, 1024 * 1024):
        view = memoryview(chunk)
        while view:
            written = os.write(target, view)
            view = view[written:]
    _ = os.lseek(source, 0, os.SEEK_SET)
    _ = os.lseek(target, 0, os.SEEK_SET)
