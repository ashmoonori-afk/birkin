"""Shared fail-closed ZIP local-header validation."""

from __future__ import annotations

import struct
import unicodedata
import zipfile
from dataclasses import dataclass
from typing import IO, cast

_LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")
_LOCAL_SIGNATURE = 0x04034B50
_DATA_DESCRIPTOR = 0x0008
_ZIP64_EXTRA = 0x0001
_UINT32_MAX = 0xFFFFFFFF


class ZipLocalHeaderError(ValueError):
    """A local header disagrees with its central-directory record."""


@dataclass(frozen=True)
class LocalHeader:
    flags: int
    compress_type: int
    crc: int
    compress_size: int
    file_size: int
    filename: str
    payload_offset: int


def _decode_name(raw: bytes, flags: int) -> str:
    try:
        return raw.decode("utf-8" if flags & 0x0800 else "cp437")
    except UnicodeDecodeError as exc:
        raise ZipLocalHeaderError("invalid ZIP local header filename") from exc


def _zip64_sizes(
    extra: bytes, file_size: int, compress_size: int
) -> tuple[int, int]:
    position = 0
    while position + 4 <= len(extra):
        identifier, length = cast(
            tuple[int, int], struct.unpack_from("<HH", extra, position)
        )
        position += 4
        end = position + length
        if end > len(extra):
            raise ZipLocalHeaderError("malformed ZIP local header extra field")
        if identifier == _ZIP64_EXTRA:
            values = extra[position:end]
            cursor = 0
            if file_size == _UINT32_MAX:
                if cursor + 8 > len(values):
                    raise ZipLocalHeaderError("malformed ZIP64 local header")
                file_size = cast(
                    tuple[int], struct.unpack_from("<Q", values, cursor)
                )[0]
                cursor += 8
            if compress_size == _UINT32_MAX:
                if cursor + 8 > len(values):
                    raise ZipLocalHeaderError("malformed ZIP64 local header")
                compress_size = cast(
                    tuple[int], struct.unpack_from("<Q", values, cursor)
                )[0]
            return file_size, compress_size
        position = end
    if file_size == _UINT32_MAX or compress_size == _UINT32_MAX:
        raise ZipLocalHeaderError("missing ZIP64 local header sizes")
    return file_size, compress_size


def read_local_header(stream: IO[bytes], info: zipfile.ZipInfo) -> LocalHeader:
    _ = stream.seek(info.header_offset)
    raw = stream.read(_LOCAL_HEADER.size)
    if len(raw) != _LOCAL_HEADER.size:
        raise ZipLocalHeaderError(f"truncated ZIP local header: {info.filename}")
    values = cast(tuple[int, ...], _LOCAL_HEADER.unpack(raw))
    if values[0] != _LOCAL_SIGNATURE:
        raise ZipLocalHeaderError(f"invalid ZIP local header: {info.filename}")
    flags, method, crc = values[2], values[3], values[6]
    compressed, uncompressed = values[7], values[8]
    name_length, extra_length = values[9], values[10]
    raw_name = stream.read(name_length)
    extra = stream.read(extra_length)
    if len(raw_name) != name_length or len(extra) != extra_length:
        raise ZipLocalHeaderError(f"truncated ZIP local header: {info.filename}")
    uncompressed, compressed = _zip64_sizes(extra, uncompressed, compressed)
    return LocalHeader(
        flags=flags,
        compress_type=method,
        crc=crc,
        compress_size=compressed,
        file_size=uncompressed,
        filename=unicodedata.normalize("NFC", _decode_name(raw_name, flags)),
        payload_offset=info.header_offset + _LOCAL_HEADER.size + name_length + extra_length,
    )


def _descriptor_matches(
    stream: IO[bytes], local: LocalHeader, info: zipfile.ZipInfo
) -> bool:
    _ = stream.seek(local.payload_offset + info.compress_size)
    raw = stream.read(24)
    offsets = [0]
    if raw.startswith(b"PK\x07\x08"):
        offsets.insert(0, 4)
    for offset in offsets:
        if len(raw) >= offset + 12:
            crc, compressed, uncompressed = cast(
                tuple[int, int, int], struct.unpack_from("<III", raw, offset)
            )
            if (crc, compressed, uncompressed) == (
                info.CRC,
                info.compress_size,
                info.file_size,
            ):
                return True
        if len(raw) >= offset + 20:
            crc64, compressed64, uncompressed64 = cast(
                tuple[int, int, int], struct.unpack_from("<IQQ", raw, offset)
            )
            if (crc64, compressed64, uncompressed64) == (
                info.CRC,
                info.compress_size,
                info.file_size,
            ):
                return True
    return False


def validate_local_headers(
    archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo]
) -> None:
    stream = archive.fp
    if stream is None:
        raise ZipLocalHeaderError("closed ZIP package")
    position = stream.tell()
    try:
        for info in infos:
            local = read_local_header(stream, info)
            central_name = unicodedata.normalize("NFC", info.filename)
            if local.flags != info.flag_bits:
                raise ZipLocalHeaderError(
                    f"ZIP local and central directory flags disagree: {info.filename}"
                )
            common_match = (
                local.compress_type == info.compress_type
                and local.filename == central_name
            )
            descriptor = bool(info.flag_bits & _DATA_DESCRIPTOR)
            crc_match = local.crc in ({0, info.CRC} if descriptor else {info.CRC})
            size_match = (
                local.compress_size in ({0, info.compress_size} if descriptor else {info.compress_size})
                and local.file_size in ({0, info.file_size} if descriptor else {info.file_size})
            )
            descriptor_match = not descriptor or _descriptor_matches(
                stream, local, info
            )
            if not common_match or not crc_match or not size_match or not descriptor_match:
                raise ZipLocalHeaderError(
                    f"ZIP local and central directory metadata disagree: {info.filename}"
                )
    finally:
        _ = stream.seek(position)
