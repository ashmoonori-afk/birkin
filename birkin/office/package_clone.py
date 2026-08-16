"""Atomic surgical ZIP cloning with untouched payload preservation."""

from __future__ import annotations

import io
import os
import struct
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import BinaryIO, cast

from .artifact_snapshot import SnapshotPath
from .errors import DocumentError, DocumentErrorCode
from .package_scan import package_invalid, preflight_package, sha256_file
from .package_types import PackageManifest, PartManifest


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise package_invalid("truncated ZIP structure")
    return data


def _central_records(stream: BinaryIO, offset: int, count: int) -> list[bytes]:
    _ = stream.seek(offset)
    records: list[bytes] = []
    for _ in range(count):
        header = _read_exact(stream, 46)
        if header[:4] != b"PK\x01\x02":
            raise package_invalid("malformed ZIP central directory")
        variable_size = sum(
            int.from_bytes(header[start : start + 2], "little")
            for start in (28, 30, 32)
        )
        record = header + _read_exact(stream, variable_size)
        if any(
            int.from_bytes(header[start : start + 4], "little") == 0xFFFFFFFF
            for start in (20, 24, 42)
        ):
            raise package_invalid("ZIP64 package cloning is unsupported")
        records.append(record)
    return records


def _patch_offset(record: bytes, offset: int) -> bytes:
    if offset > 0xFFFFFFFF:
        raise package_invalid("ZIP output exceeds classic ZIP bounds")
    patched = bytearray(record)
    struct.pack_into("<I", patched, 42, offset)
    return bytes(patched)


def _replacement_records(
    part_uri: str,
    metadata: PartManifest,
    data: bytes,
) -> tuple[bytes, bytes]:
    buffer = io.BytesIO()
    info = zipfile.ZipInfo(part_uri, metadata["date_time"])
    info.compress_type = metadata["compress_type"]
    info.external_attr = metadata["external_attr"]
    info.create_system = metadata["create_system"]
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(info, data)
        central_offset = archive.start_dir
    raw = buffer.getvalue()
    central = _central_records(io.BytesIO(raw), central_offset, 1)[0]
    return raw[:central_offset], central


def _write_clone(
    source: Path | SnapshotPath,
    destination: Path,
    manifest: PackageManifest,
    replacements: Mapping[str, bytes],
) -> None:
    ordered = sorted(manifest["parts"].items(), key=lambda item: item[1]["index"])
    with zipfile.ZipFile(source) as archive, source.open("rb") as opened_stream:
        source_stream = cast(BinaryIO, opened_stream)
        infos = archive.infolist()
        source_central = _central_records(source_stream, archive.start_dir, len(infos))
        offsets = sorted(info.header_offset for info in infos)
        if len(offsets) != len(set(offsets)) or any(
            offset < 0 or offset >= archive.start_dir for offset in offsets
        ):
            raise package_invalid("overlapping or invalid ZIP local records")
        end_by_offset = {
            offset: offsets[index + 1] if index + 1 < len(offsets) else archive.start_dir
            for index, offset in enumerate(offsets)
        }
        central_output: list[bytes] = []
        with destination.open("wb") as output_stream:
            for part_uri, metadata in ordered:
                output_offset = output_stream.tell()
                replacement = replacements.get(part_uri)
                if replacement is None:
                    _ = source_stream.seek(metadata["header_offset"])
                    local = _read_exact(
                        source_stream,
                        end_by_offset[metadata["header_offset"]]
                        - metadata["header_offset"],
                    )
                    central = source_central[metadata["index"]]
                else:
                    local, central = _replacement_records(part_uri, metadata, replacement)
                _ = output_stream.write(local)
                central_output.append(_patch_offset(central, output_offset))

            central_offset = output_stream.tell()
            for record in central_output:
                _ = output_stream.write(record)
            central_size = output_stream.tell() - central_offset
            if central_size > 0xFFFFFFFF or central_offset > 0xFFFFFFFF:
                raise package_invalid("ZIP output exceeds classic ZIP bounds")
            count = len(central_output)
            _ = output_stream.write(
                struct.pack(
                    "<IHHHHIIH",
                    0x06054B50,
                    0,
                    0,
                    count,
                    count,
                    central_size,
                    central_offset,
                    0,
                )
            )


def _verify_untouched(
    source_manifest: PackageManifest,
    output_manifest: PackageManifest,
    replacements: Mapping[str, bytes],
) -> None:
    for part_uri, metadata in source_manifest["parts"].items():
        if part_uri not in replacements and (
            output_manifest["parts"][part_uri]["original_sha256"]
            != metadata["original_sha256"]
        ):
            raise package_invalid(f"untouched part hash changed during clone: {part_uri}")


def _source_sha256(source: Path | SnapshotPath) -> str:
    if isinstance(source, SnapshotPath):
        return source.sha256()
    return sha256_file(source)


def clone_package(
    source: Path | SnapshotPath,
    output: Path,
    replacements: Mapping[str, bytes],
) -> PackageManifest:
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise DocumentError(DocumentErrorCode.OUTPUT_EXISTS, "emit", "output exists")
    manifest = preflight_package(cast(Path, cast(object, source)))
    if isinstance(source, SnapshotPath):
        manifest["source_sha256"] = source.sha256()
    if _source_sha256(source) != manifest["source_sha256"]:
        raise DocumentError(
            DocumentErrorCode.SOURCE_CHANGED,
            "emit",
            "source changed during package preflight",
        )
    missing = set(replacements) - set(manifest["parts"])
    if missing:
        raise DocumentError(
            DocumentErrorCode.NODE_NOT_FOUND,
            "locate",
            f"parts not found: {sorted(missing)}",
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=output.parent, suffix=".zip")
    os.close(descriptor)
    temporary = Path(name)
    try:
        _write_clone(source, temporary, manifest, replacements)
        _verify_untouched(manifest, preflight_package(temporary), replacements)
        if _source_sha256(source) != manifest["source_sha256"]:
            raise DocumentError(
                DocumentErrorCode.SOURCE_CHANGED,
                "emit",
                "source changed during package clone",
            )
        try:
            os.link(temporary, output)
        except FileExistsError as exc:
            raise DocumentError(
                DocumentErrorCode.OUTPUT_EXISTS,
                "emit",
                "output exists",
            ) from exc
        temporary.unlink()
        return manifest
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
