"""Native Windows creation for exact directory handles."""

from __future__ import annotations

from pathlib import Path


def rename_handle(
    source_handle: int,
    parent_handle: int,
    parent_path: Path,
    name: str,
) -> None:
    import ctypes
    from ctypes import wintypes

    class StatusValue(ctypes.Union):
        _fields_ = [
            ("Status", ctypes.c_long),
            ("Pointer", ctypes.c_void_p),
        ]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [
            ("value", StatusValue),
            ("Information", ctypes.c_size_t),
        ]

    class FileRenameInformation(ctypes.Structure):
        _fields_ = [
            ("ReplaceIfExists", wintypes.BOOLEAN),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        ]

    encoded = (name + "\0").encode("utf-16-le")
    offset = FileRenameInformation.FileName.offset
    buffer = ctypes.create_string_buffer(
        ctypes.sizeof(FileRenameInformation) + len(encoded)
    )
    info = FileRenameInformation.from_buffer(buffer)
    info.ReplaceIfExists = False
    info.RootDirectory = wintypes.HANDLE(parent_handle)
    info.FileNameLength = len(name.encode("utf-16-le"))
    ctypes.memmove(
        ctypes.addressof(buffer) + offset,
        encoded,
        len(encoded),
    )
    ntdll = ctypes.WinDLL("ntdll")
    set_information = ntdll.NtSetInformationFile
    set_information.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(IoStatusBlock),
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    set_information.restype = ctypes.c_long
    status_block = IoStatusBlock()
    status = set_information(
        wintypes.HANDLE(source_handle),
        ctypes.byref(status_block),
        buffer,
        len(buffer),
        10,
    )
    if status < 0:
        convert_status = ntdll.RtlNtStatusToDosError
        convert_status.argtypes = [ctypes.c_long]
        convert_status.restype = wintypes.ULONG
        raise OSError(
            int(convert_status(status)) or 1,
            str(parent_path / name),
        )


def create_directory_handle(
    parent_handle: int,
    parent_path: Path,
    name: str,
    *,
    access: int,
    share: int,
) -> int:
    import ctypes
    from ctypes import wintypes

    class StatusValue(ctypes.Union):
        _fields_ = [
            ("Status", ctypes.c_long),
            ("Pointer", ctypes.c_void_p),
        ]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [
            ("value", StatusValue),
            ("Information", ctypes.c_size_t),
        ]

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(UnicodeString)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        ]

    encoded = name.encode("utf-16-le")
    name_buffer = ctypes.create_unicode_buffer(name)
    object_name = UnicodeString(
        len(encoded),
        len(encoded) + ctypes.sizeof(wintypes.WCHAR),
        ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = ObjectAttributes(
        ctypes.sizeof(ObjectAttributes),
        wintypes.HANDLE(parent_handle),
        ctypes.pointer(object_name),
        0x00000040,
        None,
        None,
    )
    ntdll = ctypes.WinDLL("ntdll")
    create_file = ntdll.NtCreateFile
    create_file.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatusBlock),
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    create_file.restype = ctypes.c_long
    handle = wintypes.HANDLE()
    status_block = IoStatusBlock()
    status = create_file(
        ctypes.byref(handle),
        access,
        ctypes.byref(attributes),
        ctypes.byref(status_block),
        None,
        0x00000080,
        share,
        2,
        0x00000001,
        None,
        0,
    )
    if status < 0:
        convert_status = ntdll.RtlNtStatusToDosError
        convert_status.argtypes = [ctypes.c_long]
        convert_status.restype = wintypes.ULONG
        raise OSError(
            int(convert_status(status)) or 1,
            str(parent_path / name),
        )
    if handle.value is None:
        raise OSError(1, str(parent_path / name))
    return int(handle.value)
