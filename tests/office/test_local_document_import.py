from __future__ import annotations

import hashlib
import json
import os
import unicodedata
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from openpyxl import Workbook

from birkin import approvals, store
from birkin.native import jailed_import
from birkin.office import local_import
from birkin.office.errors import DocumentError, DocumentErrorCode
from birkin.office.service import DocumentService
from birkin.tools import ToolRegistry, build_registry
from birkin.tools._types import ToolContext
from tests.office.fixture_builders import build_docx_template

_POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")


def _xlsx(path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Revenue"
    sheet["A1"] = 7
    workbook.save(path)
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registry(cwd: Path) -> ToolRegistry:
    return build_registry(
        ToolContext(cfg={}, client=None, cwd=cwd, record_source="user:local-import"),
        include={"documents"},
    )


def _call(
    registry: ToolRegistry, name: str, data: dict[str, object]
) -> tuple[dict[str, object], bool]:
    result = registry.execute(name, data)
    content = cast(str, result.content)
    return cast("dict[str, object]", json.loads(content)), bool(result.is_error)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home"
    monkeypatch.setenv("BIRKIN_HOME", str(path))
    return path


@pytest.fixture
def cwd(tmp_path: Path) -> Path:
    path = tmp_path / "cwd"
    path.mkdir()
    return path


def _drafts(home: Path) -> list[str]:
    drafts = home / "office" / "artifacts" / "drafts"
    return sorted(item.name for item in drafts.iterdir()) if drafts.is_dir() else []


def test_workspace_file_is_copied_into_the_jail_without_leaking_its_path(
    home: Path, cwd: Path
) -> None:
    # Given: a Korean-named workbook in the user's working folder.
    source = _xlsx(cwd / "매출.xlsx")
    before = source.read_bytes()
    registry = _registry(cwd)

    # When: the model imports it by its relative path.
    body, is_error = _call(registry, "local_document_import", {"path": "매출.xlsx"})

    # Then: the copy is a managed draft with the source's exact bytes.
    assert not is_error, body
    artifact = cast("dict[str, str]", body["artifact"])
    receipt = cast("dict[str, object]", body["receipt"])
    drafts = (home / "office" / "artifacts" / "drafts").resolve()
    assert Path(artifact["uri"]).parent == drafts
    assert artifact["content_hash"] == hashlib.sha256(before).hexdigest()
    assert receipt["copied"] is True
    assert body["source_filename"] == "매출.xlsx"
    serialized = json.dumps(body, ensure_ascii=False)
    assert str(source) not in serialized
    assert str(cwd) not in serialized

    inspected, inspect_error = _call(registry, "inspect_document", {"source": artifact})
    assert not inspect_error, inspected
    assert inspected["format"] == "xlsx"
    assert source.read_bytes() == before


def test_reimporting_identical_bytes_reuses_the_existing_draft(
    home: Path, cwd: Path
) -> None:
    _ = _xlsx(cwd / "매출.xlsx")
    registry = _registry(cwd)
    first, _ = _call(registry, "local_document_import", {"path": "매출.xlsx"})
    drafts = _drafts(home)

    second, is_error = _call(registry, "local_document_import", {"path": "매출.xlsx"})

    assert not is_error, second
    assert cast("dict[str, str]", second["artifact"])["uri"] == cast(
        "dict[str, str]", first["artifact"]
    )["uri"]
    assert cast("dict[str, object]", second["receipt"])["copied"] is False
    assert _drafts(home) == drafts


def test_name_collision_with_different_bytes_is_still_refused(home: Path, cwd: Path) -> None:
    # Given: a managed draft already holding other bytes under the import name.
    service = DocumentService(home / "office")
    source = _xlsx(cwd / "a.xlsx")
    digest = _sha256(source)
    _ = (service._workspace.drafts / "a.xlsx").write_bytes(b"other bytes")

    # When/Then: reuse applies only to identical content.
    with pytest.raises(DocumentError) as raised:
        _ = service.import_document(
            source, expected_sha256=digest, output_name="a.xlsx", reuse_identical=True
        )
    assert raised.value.code is DocumentErrorCode.OUTPUT_EXISTS


def _outside(tmp_path: Path, cwd: Path) -> str:
    _ = (tmp_path / "outside.docx").write_bytes(b"outside")
    return "../outside.docx"


def _absolute_outside(tmp_path: Path, cwd: Path) -> str:
    target = tmp_path / "outside.docx"
    _ = target.write_bytes(b"outside")
    return str(target)


def _symlinked_file(tmp_path: Path, cwd: Path) -> str:
    target = tmp_path / "outside.docx"
    _ = target.write_bytes(b"outside")
    (cwd / "link.docx").symlink_to(target)
    return "link.docx"


def _symlinked_parent(tmp_path: Path, cwd: Path) -> str:
    outer = tmp_path / "outer"
    outer.mkdir()
    _ = (outer / "inner.docx").write_bytes(b"outside")
    (cwd / "linked").symlink_to(outer, target_is_directory=True)
    return "linked/inner.docx"


def _directory(tmp_path: Path, cwd: Path) -> str:
    (cwd / "x.docx").mkdir()
    return "x.docx"


def _missing(tmp_path: Path, cwd: Path) -> str:
    return "missing.docx"


def _legacy_hwp(tmp_path: Path, cwd: Path) -> str:
    _ = (cwd / "a.hwp").write_bytes(b"legacy")
    return "a.hwp"


def _text_file(tmp_path: Path, cwd: Path) -> str:
    _ = (cwd / "notes.txt").write_text("notes", encoding="utf-8")
    return "notes.txt"


@pytest.mark.parametrize(
    ("make_path", "code"),
    [
        (_outside, "PERMISSION_DENIED"),
        (_absolute_outside, "PERMISSION_DENIED"),
        pytest.param(_symlinked_file, "PERMISSION_DENIED", marks=_POSIX_ONLY),
        pytest.param(_symlinked_parent, "PERMISSION_DENIED", marks=_POSIX_ONLY),
        (_directory, "INVALID_INPUT"),
        (_missing, "INVALID_INPUT"),
        (_legacy_hwp, "UNSUPPORTED_FORMAT"),
        (_text_file, "UNSUPPORTED_FORMAT"),
    ],
)
def test_unsafe_or_unsupported_paths_are_refused_without_a_draft(
    home: Path,
    cwd: Path,
    tmp_path: Path,
    make_path: Callable[[Path, Path], str],
    code: str,
) -> None:
    path = make_path(tmp_path, cwd)

    body, is_error = _call(_registry(cwd), "local_document_import", {"path": path})

    assert is_error, body
    assert cast("dict[str, object]", body["error"])["code"] == code
    assert _drafts(home) == []


def test_oversized_file_is_refused_before_any_copy(
    home: Path, cwd: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = _xlsx(cwd / "big.xlsx")
    monkeypatch.setattr(local_import, "MAX_IMPORT_BYTES", 10)

    body, is_error = _call(_registry(cwd), "local_document_import", {"path": "big.xlsx"})

    assert is_error, body
    assert cast("dict[str, object]", body["error"])["code"] == "LIMIT_EXCEEDED"
    assert _drafts(home) == []


def test_import_cap_matches_the_web_import_boundary() -> None:
    assert local_import.MAX_IMPORT_BYTES == jailed_import.MAX_IMPORT_BYTES


@pytest.mark.parametrize(
    "relative",
    [
        "home/office/artifacts/export-backups/x.docx",
        "home/x.docx",
        "HOME/Office/Artifacts/Drafts/x.docx",
    ],
)
def test_birkin_state_is_never_imported_from_a_parent_workspace(
    home: Path, tmp_path: Path, relative: str
) -> None:
    # Given: the working folder is the parent of BIRKIN_HOME.
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    _ = target.write_bytes(b"birkin state")

    # When: the model names a Birkin-owned file through the workspace.
    body, is_error = _call(_registry(tmp_path), "local_document_import", {"path": relative})

    # Then: it is refused as Birkin state, whatever the spelling.
    assert is_error, body
    error = cast("dict[str, object]", body["error"])
    assert error["code"] == "PERMISSION_DENIED"
    assert cast("dict[str, object]", error["details"])["reason"] == "birkin_state"


@_POSIX_ONLY
def test_a_drop_folder_redirected_into_birkin_state_is_refused(
    home: Path, cwd: Path
) -> None:
    backups = home / "office" / "artifacts" / "export-backups"
    backups.mkdir(parents=True)
    _ = (backups / "x.docx").write_bytes(b"backup")
    (home / "uploads").symlink_to(backups, target_is_directory=True)

    body, is_error = _call(
        _registry(cwd), "local_document_import", {"path": str(home / "uploads" / "x.docx")}
    )

    assert is_error, body
    error = cast("dict[str, object]", body["error"])
    assert cast("dict[str, object]", error["details"])["reason"] == "birkin_state"


def test_telegram_upload_and_drop_folder_files_import(home: Path, cwd: Path) -> None:
    uploads = home / "uploads"
    incoming = home / "office" / "artifacts" / "incoming"
    uploads.mkdir(parents=True)
    incoming.mkdir(parents=True)
    upload = build_docx_template(uploads / "abc_보고서.docx")
    dropped = _xlsx(incoming / "매출.xlsx")
    registry = _registry(cwd)

    for path in (upload, dropped):
        body, is_error = _call(registry, "local_document_import", {"path": str(path)})
        assert not is_error, body
        artifact = cast("dict[str, str]", body["artifact"])
        assert artifact["content_hash"] == _sha256(path)
        inspected, inspect_error = _call(registry, "inspect_document", {"source": artifact})
        assert not inspect_error, inspected


def test_nfd_and_long_korean_names_become_bounded_nfc_jail_names(
    home: Path, cwd: Path
) -> None:
    nfd_name = unicodedata.normalize("NFD", "계약서.docx")
    long_stem = "가" * 80
    _ = build_docx_template(cwd / nfd_name)
    _ = build_docx_template(cwd / f"{long_stem}.docx")
    registry = _registry(cwd)

    short, short_error = _call(registry, "local_document_import", {"path": nfd_name})
    long, long_error = _call(registry, "local_document_import", {"path": f"{long_stem}.docx"})

    assert not short_error and not long_error, (short, long)
    short_name = Path(cast("dict[str, str]", short["artifact"])["uri"]).name
    digest = cast("dict[str, str]", short["artifact"])["content_hash"]
    assert short_name == f"계약서-{digest[:12]}.docx"
    assert short_name == unicodedata.normalize("NFC", short_name)
    assert short["source_filename"] == "계약서.docx"
    long_name = Path(cast("dict[str, str]", long["artifact"])["uri"]).name
    assert long_name.startswith("가" * 40 + "-")
    assert len(long_name.split("-")[0].encode("utf-8")) == 120


def test_imported_docx_is_filled_and_exported_after_approval(
    home: Path, cwd: Path
) -> None:
    # Given: a DOCX template in the working folder, imported into the jail.
    source = build_docx_template(cwd / "견적서.docx")
    source_sha256 = _sha256(source)
    registry = _registry(cwd)
    imported, _ = _call(registry, "local_document_import", {"path": "견적서.docx"})

    # When: a field fill is requested and approved.
    proposed, is_error = _call(registry, "office_job_request", {
        "request": "견적서.docx Word 문서의 customer 필드를 채워줘",
        "source": imported["artifact"],
        "outcome": "견적서 고객명 채우기",
        "operations": [{"field": "customer", "value": "홍길동"}],
        "destination": str(cwd / "견적서-완성.docx"),
    })
    assert not is_error, proposed
    record = store.get_pending(cast(str, proposed["id"]))
    assert record is not None
    assert record["description"] == "DOCX 필드 'customer' 변경: PLACEHOLDER → 홍길동"
    result = approvals.approve(
        cast(str, proposed["id"]), approved_by="human:test", approved_via="test:local-import"
    )

    # Then: the export lands in the working folder and the original is unchanged.
    assert result["ok"] is True, result
    with zipfile.ZipFile(cwd / "견적서-완성.docx") as package:
        assert "홍길동" in package.read("word/document.xml").decode("utf-8")
    assert _sha256(source) == source_sha256
