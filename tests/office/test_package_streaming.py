from __future__ import annotations

import zipfile
from pathlib import Path
from typing import ClassVar

import pytest

from birkin.office import package_scan
from birkin.office.extract_package import extract_package_items


def test_package_extraction_retains_only_bounded_entry_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "bounded.docx"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            b"<document><p><t>done</t></p></document>",
        )
        for index in range(8):
            archive.writestr(
                f"custom/late-{index}.bin",
                bytes([index]) * 1024,
            )

    class TrackedBytes(bytes):
        alive: ClassVar[int] = 0
        peak: ClassVar[int] = 0

        def __new__(cls, payload: bytes) -> TrackedBytes:
            instance = super().__new__(cls, payload)
            cls.alive += 1
            cls.peak = max(cls.peak, cls.alive)
            return instance

        def __del__(self) -> None:
            type(self).alive -= 1

    original_read = package_scan._read_verified

    def tracked_read(
        archive: zipfile.ZipFile,
        info: zipfile.ZipInfo,
    ) -> bytes:
        return TrackedBytes(original_read(archive, info))

    monkeypatch.setattr(package_scan, "_read_verified", tracked_read)

    items = extract_package_items(
        source,
        "docx",
        max_text_bytes=4,
    )

    assert [item["text"] for item in items] == ["done"]
    assert TrackedBytes.peak <= 3
    assert TrackedBytes.alive == 0
