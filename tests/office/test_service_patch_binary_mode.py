from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path
from typing import cast

import pytest

from birkin.office.service import DocumentService
from tests.office.fixture_builders import build_docx_template


def _exercise_patch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, binary_flag: int | None
) -> tuple[list[int], bytes]:
    source = build_docx_template(tmp_path / "source.docx")
    source_bytes = source.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    drafts = tmp_path / "artifacts" / "drafts"
    real_open = os.open
    native_binary_flag = getattr(os, "O_BINARY", 0)
    candidate_flags: list[int] = []

    if binary_flag is None:
        monkeypatch.delattr(os, "O_BINARY", raising=False)
    else:
        monkeypatch.setattr(os, "O_BINARY", binary_flag, raising=False)

    def recording_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        candidate = Path(os.fsdecode(path))
        if (
            candidate.parent == drafts
            and candidate.suffix == ".docx"
            and flags & os.O_WRONLY
        ):
            candidate_flags.append(flags)
        native_flags = (flags & ~(binary_flag or 0)) | native_binary_flag
        if dir_fd is None:
            return real_open(path, native_flags, mode)
        return real_open(path, native_flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", recording_open)
    result = DocumentService(tmp_path).apply_document_patch(
        {"uri": str(source), "content_hash": digest},
        {"operations": [{"field": "customer", "value": "Ada"}]},
        expected_source_sha256=digest,
        output_name="patched.docx",
        dry_run=False,
    )
    artifact = cast("dict[str, str]", result["draft_artifact"])
    output = Path(artifact["uri"])
    assert source.read_bytes() == source_bytes
    with zipfile.ZipFile(output) as archive:
        assert b"Ada" in archive.read("word/document.xml")
    return candidate_flags, output.read_bytes()


def test_patch_candidate_descriptor_uses_o_binary_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    simulated_o_binary = 1 << 29
    flags, payload = _exercise_patch(
        tmp_path, monkeypatch, binary_flag=simulated_o_binary
    )

    assert len(flags) == 1
    assert flags[0] & simulated_o_binary
    assert payload.startswith(b"PK")


def test_patch_candidate_descriptor_preserves_posix_flags_and_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flags, payload = _exercise_patch(tmp_path, monkeypatch, binary_flag=None)

    assert flags == [os.O_WRONLY | getattr(os, "O_CLOEXEC", 0)]
    assert payload.startswith(b"PK")
