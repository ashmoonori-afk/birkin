from __future__ import annotations

from pathlib import Path

import pytest

from birkin import private_storage_windows_handle


class _FakeWindowsFileApi:
    def __init__(self) -> None:
        self.attributes = 0
        self.file_type = 1
        self.dacl_error: OSError | None = None
        self.transfer_error: OSError | None = None
        self.create_arguments: tuple[int, int, int, int] | None = None
        self.events: list[str] = []
        self.closed_handles: list[int] = []

    def create_file(
        self,
        path: Path,
        *,
        desired_access: int,
        share_mode: int,
        creation_disposition: int,
        flags_and_attributes: int,
    ) -> int:
        del path
        self.create_arguments = (
            desired_access,
            share_mode,
            creation_disposition,
            flags_and_attributes,
        )
        self.events.append("create")
        return 73

    def get_file_type(self, handle: int) -> int:
        del handle
        self.events.append("type")
        return self.file_type

    def get_file_attributes(self, handle: int) -> int:
        del handle
        self.events.append("attributes")
        return self.attributes

    def set_owner_only_dacl(self, handle: int) -> None:
        del handle
        self.events.append("dacl")
        if self.dacl_error is not None:
            raise self.dacl_error

    def open_osfhandle(self, handle: int) -> int:
        del handle
        self.events.append("transfer")
        if self.transfer_error is not None:
            raise self.transfer_error
        return 91

    def close_handle(self, handle: int) -> None:
        self.events.append("close")
        self.closed_handles.append(handle)


def test_windows_private_read_requests_read_and_dacl_access() -> None:
    api = _FakeWindowsFileApi()

    descriptor = private_storage_windows_handle._open_windows_private_file(
        Path("gateway_http_token"),
        api,
    )

    assert descriptor == 91
    assert api.create_arguments == (
        private_storage_windows_handle._GENERIC_READ
        | private_storage_windows_handle._READ_CONTROL
        | private_storage_windows_handle._WRITE_DAC,
        private_storage_windows_handle._FILE_SHARE_READ
        | private_storage_windows_handle._FILE_SHARE_WRITE
        | private_storage_windows_handle._FILE_SHARE_DELETE,
        private_storage_windows_handle._OPEN_EXISTING,
        private_storage_windows_handle._FILE_ATTRIBUTE_NORMAL
        | private_storage_windows_handle._FILE_FLAG_OPEN_REPARSE_POINT,
    )
    assert api.events == [
        "create",
        "type",
        "attributes",
        "dacl",
        "transfer",
    ]
    assert api.closed_handles == []


def test_windows_private_read_refuses_reparse_handle() -> None:
    api = _FakeWindowsFileApi()
    api.attributes = (
        private_storage_windows_handle._FILE_ATTRIBUTE_REPARSE_POINT
    )

    with pytest.raises(OSError, match="reparse"):
        _ = private_storage_windows_handle._open_windows_private_file(
            Path("gateway_http_token"),
            api,
        )

    assert api.events == ["create", "type", "attributes", "close"]
    assert api.closed_handles == [73]


def test_windows_private_read_refuses_directory_handle() -> None:
    api = _FakeWindowsFileApi()
    api.attributes = private_storage_windows_handle._FILE_ATTRIBUTE_DIRECTORY

    with pytest.raises(OSError, match="regular file"):
        _ = private_storage_windows_handle._open_windows_private_file(
            Path("gateway_http_token"),
            api,
        )

    assert api.events == ["create", "type", "attributes", "close"]
    assert api.closed_handles == [73]


def test_windows_private_read_closes_handle_on_dacl_failure() -> None:
    api = _FakeWindowsFileApi()
    api.dacl_error = OSError("sentinel DACL failure")

    with pytest.raises(OSError, match="sentinel DACL failure"):
        _ = private_storage_windows_handle._open_windows_private_file(
            Path("gateway_http_token"),
            api,
        )

    assert api.events == [
        "create",
        "type",
        "attributes",
        "dacl",
        "close",
    ]
    assert api.closed_handles == [73]


def test_windows_private_read_closes_handle_on_conversion_failure() -> None:
    api = _FakeWindowsFileApi()
    api.transfer_error = OSError("sentinel conversion failure")

    with pytest.raises(OSError, match="sentinel conversion failure"):
        _ = private_storage_windows_handle._open_windows_private_file(
            Path("gateway_http_token"),
            api,
        )

    assert api.events == [
        "create",
        "type",
        "attributes",
        "dacl",
        "transfer",
        "close",
    ]
    assert api.closed_handles == [73]
