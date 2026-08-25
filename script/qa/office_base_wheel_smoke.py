"""Exercise baseline Office behavior from a base-only installed wheel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import cast
from unittest.mock import patch


def _reference(path: Path) -> dict[str, str]:
    return {
        "uri": str(path),
        "content_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _managed_fixture(source: Path, incoming: Path) -> dict[str, str]:
    target = incoming / source.name
    _ = shutil.copyfile(source, target)
    return _reference(target)


def fixture_sources(fixtures: Path) -> Mapping[str, Path]:
    office = fixtures / "office"
    generated = office / "sources"
    drafts = office / "artifacts" / "drafts"
    return {
        "docx": drafts / "created-docx.docx",
        "xlsx": drafts / "created-xlsx.xlsx",
        "pptx": drafts / "created-pptx.pptx",
        "pdf": drafts / "created-pdf.pdf",
        "hwpx": generated / "source.hwpx",
    }


def run(home: Path, fixtures: Path) -> dict[str, object]:
    with (
        patch.object(
            socket,
            "socket",
            side_effect=AssertionError("Office attempted network access"),
        ),
        patch.object(
            subprocess,
            "Popen",
            side_effect=AssertionError("Office attempted process launch"),
        ),
        patch.object(
            subprocess,
            "run",
            side_effect=AssertionError("Office attempted process launch"),
        ),
    ):
        from birkin import config
        from birkin.office.conversion_schema import LOSS_CATEGORIES
        from birkin.office.errors import DocumentError, DocumentErrorCode
        from birkin.office.service import DocumentService
        from birkin.office.skill_router import route_office_request
        from birkin.skills.loader import discover
        from birkin.tools.documents import NAMES

        incoming = home / "artifacts" / "incoming"
        incoming.mkdir(parents=True)
        sources = fixture_sources(fixtures)
        references = {
            format_name: _managed_fixture(source, incoming)
            for format_name, source in sources.items()
        }
        service = DocumentService(home)
        operations: dict[str, dict[str, object]] = {}
        loss_budget = {category: 100 for category in LOSS_CATEGORIES}
        for format_name, reference in references.items():
            inspection = service.inspect_document(reference)
            validation = service.validate_artifact(reference)
            comparison = service.compare_documents(reference, reference)
            format_result: dict[str, object] = {
                "inspect": bool(inspection),
                "validate": bool(validation),
                "compare": bool(comparison),
            }
            try:
                extraction = service.extract_document(
                    reference,
                    max_spans=1000,
                    max_nodes=1000,
                    max_text_bytes=100_000,
                )
                format_result["extract"] = bool(extraction)
                conversion = service.convert_document(
                    reference,
                    target_format="txt",
                    output_name=f"{format_name}.txt",
                    loss_budget=loss_budget,
                )
                format_result["convert"] = bool(conversion)
            except DocumentError as exc:
                if format_name != "pdf":
                    raise
                assert exc.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE
                format_result["extract"] = "conditional"
                format_result["convert"] = "conditional"
            operations[format_name] = format_result

        created_pdf = service.create_document(
            format="pdf",
            content={"paragraphs": ["base wheel PDF"]},
            output_name="base.pdf",
        )
        derived_hwpx = service.create_document(
            format="hwpx",
            content={"bindings": {"customer": "Base wheel"}},
            output_name="derived.hwpx",
            template=references["hwpx"],
        )
        unavailable: list[str] = []
        create_content: dict[str, dict[str, object]] = {
            "docx": {"paragraphs": ["optional backend"]},
            "xlsx": {
                "sheets": [{"name": "Sheet1", "rows": [["optional backend"]]}]
            },
            "pptx": {
                "slides": [{"title": "Optional backend", "body": "local only"}]
            },
            "hwpx": {"paragraphs": ["optional backend"]},
        }
        for format_name in ("docx", "xlsx", "pptx", "hwpx"):
            try:
                _ = service.create_document(
                    format=format_name,
                    content=create_content[format_name],
                    output_name=f"optional.{format_name}",
                )
            except DocumentError as exc:
                assert exc.code is DocumentErrorCode.CAPABILITY_UNAVAILABLE
                unavailable.append(format_name)
            else:
                raise AssertionError(
                    f"{format_name} blank creation unexpectedly lacked an optional boundary"
                )

        required_skills = {
            "office-work-os",
            "office-documents",
            "word-documents",
            "spreadsheets",
            "presentations",
            "pdf-documents",
            "korean-hwp-documents",
        }
        skills = discover(
            [
                (path, "bundled")
                for path in config.bundled_skills_dirs()
                if path.name == "_bundled_skills"
            ]
        )
        tool_names = set(NAMES)
        route = route_office_request("HWPX 서식 채워줘")
        assert route is not None
        return {
            "ok": True,
            "operations": operations,
            "base_create": {
                "pdf": cast(str, created_pdf["creation_mode"]),
                "hwpx": cast(str, derived_hwpx["creation_mode"]),
            },
            "optional_create_refusals": unavailable,
            "skills": sorted(required_skills & skills.keys()),
            "route": route.skill_name,
            "tools": sorted(tool_names),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--home", required=True, type=Path)
    _ = parser.add_argument("--fixtures", required=True, type=Path)
    args = parser.parse_args()
    for key in tuple(os.environ):
        if key.endswith("_API_KEY") or key.endswith("_TOKEN"):
            _ = os.environ.pop(key, None)
    report = run(cast(Path, args.home), cast(Path, args.fixtures))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
