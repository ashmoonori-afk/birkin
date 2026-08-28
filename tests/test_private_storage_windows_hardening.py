from __future__ import annotations

from pathlib import Path

import pytest

from birkin import private_storage_windows_handle as handle_api
from birkin import private_storage_windows_hardening as hardening
from birkin.native import private_storage_windows as native_hardening


class _FakeApi:
    def __init__(self, *, reparse: Path | None = None) -> None:
        self.reparse = reparse
        self.paths: dict[int, Path] = {}
        self.closed: list[int] = []
        self.hardened: list[tuple[Path, bool]] = []

    def create_file(
        self,
        path: Path,
        *,
        desired_access: int,
        share_mode: int,
        creation_disposition: int,
        flags_and_attributes: int,
    ) -> int:
        del desired_access, share_mode, creation_disposition, flags_and_attributes
        value = len(self.paths) + 1
        self.paths[value] = path
        return value

    def get_file_type(self, handle: int) -> int:
        del handle
        return handle_api._FILE_TYPE_DISK

    def get_file_attributes(self, handle: int) -> int:
        path = self.paths[handle]
        attributes = (
            handle_api._FILE_ATTRIBUTE_DIRECTORY
            if path != Path("/safe/home/key")
            else 0
        )
        if path == self.reparse:
            attributes |= handle_api._FILE_ATTRIBUTE_REPARSE_POINT
        return attributes

    def set_owner_only_dacl(
        self,
        handle: int,
        *,
        directory: bool,
    ) -> None:
        self.hardened.append((self.paths[handle], directory))

    def open_osfhandle(self, handle: int) -> int:
        return handle

    def close_handle(self, handle: int) -> None:
        self.closed.append(handle)


def test_native_windows_hardening_shim_exports_handle_bound_implementation() -> None:
    assert native_hardening.harden_windows_path is (
        hardening.harden_windows_path_by_handle
    )


def test_windows_hardening_applies_dacl_through_final_handle() -> None:
    api = _FakeApi()

    hardening._harden_windows_path(
        Path("/safe/home/key"),
        directory=False,
        api=api,
    )

    assert api.hardened == [(Path("/safe/home/key"), False)]
    assert api.closed == list(api.paths)


def test_windows_hardening_rejects_reparse_ancestor() -> None:
    target = Path("/safe/home/key")
    api = _FakeApi(reparse=target.absolute().parents[1])

    with pytest.raises(OSError, match="reparse point"):
        hardening._harden_windows_path(
            target,
            directory=False,
            api=api,
        )

    assert api.hardened == []
    assert api.closed == list(api.paths)
