from __future__ import annotations

from pathlib import Path

from birkin.office.search import search_sources
from birkin.office.service import DocumentService


def test_search_returns_live_locator_version_and_drops_revoked_source(tmp_path: Path) -> None:
    service = DocumentService(tmp_path)
    first = service.create_document(
        format="docx", content={"paragraphs": ["분기 매출은 42입니다."]}, output_name="old.docx"
    )["draft_artifact"]
    second = service.create_document(
        format="docx", content={"paragraphs": ["비공개 매출은 99입니다."]}, output_name="revoked.docx"
    )["draft_artifact"]

    result = search_sources(
        "매출",
        [
            {"artifact": first, "scope": "current_work", "access_granted": True, "label": "report.docx", "version": "v1", "current_version": "v2"},
            {"artifact": second, "scope": "allowed_connection", "access_granted": False, "label": "secret.docx", "version": "v1"},
        ],
        extract=service.extract_document,
    )

    assert result["excluded_sources"] == 1 and result["cache"] == "none"
    hit = result["results"][0]
    assert hit["file"] == "report.docx" and hit["is_older_version"] is True
    assert hit["source_sha256"] == first["content_hash"]
    assert hit["source_locator"]["document"].startswith("sha256:")
    assert len(hit["source_locator"]) > 1
    assert "99" not in str(result)

    Path(first["uri"]).unlink()
    after_delete = search_sources(
        "매출",
        [{"artifact": first, "scope": "current_work", "access_granted": True, "version": "v1"}],
        extract=service.extract_document,
    )
    assert after_delete["results"] == [] and after_delete["excluded_sources"] == 1
