from __future__ import annotations

import os
from pathlib import Path

import pytest


def create_symlink(
    link: Path, target: Path, *, target_is_directory: bool = False
) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as error:
        if os.name == "nt" and error.winerror == 1314:
            pytest.skip("Windows symlink creation requires SeCreateSymbolicLinkPrivilege")
        raise
