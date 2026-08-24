"""Offline, real-document dogfood for the registered Office Work OS tools."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_approvals = importlib.import_module("birkin.approvals")
_errors = importlib.import_module("birkin.office.errors")
_service = importlib.import_module("birkin.office.service")
_tools = importlib.import_module("birkin.tools")
_tool_types = importlib.import_module("birkin.tools._types")
_dogfood_fixtures = importlib.import_module("script.qa.office_dogfood_fixtures")

approve = _approvals.approve
DocumentError = _errors.DocumentError
DocumentService = _service.DocumentService
build_registry = _tools.build_registry
ToolContext = _tool_types.ToolContext
artifact = _dogfood_fixtures.artifact
extracted_text = _dogfood_fixtures.extracted_text
hwpx_fixture = _dogfood_fixtures.hwpx_fixture
receipt = _dogfood_fixtures.receipt
reopen = _dogfood_fixtures.reopen
sha256 = _dogfood_fixtures.sha256

FORMATS = ("docx", "xlsx", "pptx", "pdf", "hwpx")
CONTENT: dict[str, dict[str, object]] = {
    "docx": {"paragraphs": ["Dogfood DOCX evidence", "PLACEHOLDER"]},
    "xlsx": {"sheets": [{"name": "Evidence", "rows": [["Dogfood XLSX evidence"], [42]]}]},
    "pptx": {"slides": [{"title": "Dogfood PPTX evidence", "body": "PLACEHOLDER"}]},
    "pdf": {"paragraphs": ["Dogfood PDF evidence"]},
}
PATCHES: dict[str, dict[str, object]] = {
    "docx": {
        "locator": {"format": "docx", "index": 2},
        "value": "Dogfood DOCX modified",
    },
    "hwpx": {"field": "customer", "value": "Dogfood HWPX modified"},
}


def run(output_dir: Path) -> dict[str, object]:
    jail = output_dir.expanduser().resolve()
    jail.mkdir(parents=True, exist_ok=True)
    if not jail.is_dir():
        raise ValueError("output directory is not a directory")
    os.environ["BIRKIN_HOME"] = str(jail)
    registry = build_registry(
        ToolContext(cfg={"spill_threshold": 1_000_000}, client=None, cwd=jail),
        include={"documents"},
    )
    service = DocumentService(jail)
    coordinated = jail / "coordinated"
    coordinated.mkdir(exist_ok=True)

    def call(
        name: str, data: dict[str, object], *, refusal: bool = False
    ) -> dict[str, object]:
        result = registry.execute(name, data)
        if not isinstance(result.content, str):
            raise TypeError(f"{name} returned non-JSON content")
        body = cast(dict[str, object], json.loads(result.content))
        if result.is_error != refusal:
            state = "refusal" if result.is_error else "success"
            raise AssertionError(f"{name}: unexpected {state}: {body}")
        return body

    def coordinate(
        format_name: str,
        source: dict[str, str],
        operation: dict[str, object],
    ) -> dict[str, str]:
        destination = coordinated / f"modified-{format_name}.{format_name}"
        proposed = call(
            "office_job_request",
            {
                "request": f"Update this {format_name} Office document",
                "source": source,
                "outcome": f"Apply the approved {format_name} dogfood edit",
                "operations": [operation],
                "destination": str(destination),
            },
        )
        approved = approve(cast(str, proposed["id"]))
        if approved["ok"] is not True:
            raise AssertionError(f"office_job_request approval failed: {approved}")
        return artifact(destination)

    inventory = cast(
        list[dict[str, object]], call("list_document_adapters", {})["adapters"]
    )
    by_format = {str(item["format"]): item for item in inventory}
    sources = jail / "sources"
    sources.mkdir(exist_ok=True)
    evidence: dict[str, dict[str, object]] = {}
    refusals: list[dict[str, object]] = []
    for fmt in FORMATS:
        fixture_kind = "birkin_create"
        if fmt == "hwpx":
            source_path = sources / "source.hwpx"
            hwpx_fixture(source_path)
            source = artifact(source_path)
            fixture_kind = "standards_fixture_not_birkin_create"
            created = cast(dict[str, str], service.create_document(
                format="hwpx",
                content={"bindings": {"customer": "Dogfood HWPX created"}},
                output_name="created-hwpx.hwpx",
                template=source,
            )["draft_artifact"])
        else:
            created = cast(dict[str, str], service.create_document(
                format=fmt,
                content=CONTENT[fmt],
                output_name=f"created-{fmt}.{fmt}",
            )["draft_artifact"])
            source = created
            fixture_kind = "deterministic_birkin_fixture"
        source_path = Path(source["uri"])
        before = sha256(source_path)
        operations: dict[str, object] = {"create": {"status": "ok", "artifact": created["content_hash"]}}
        operations["inspect"] = {"status": "ok", "result": call("inspect_document", {"source": source})["format"]}
        extracted = call("extract_document", {"source": source})
        spans = cast(list[object], extracted["spans"])
        operations["extract"] = {"status": "ok", "spans": len(spans)}
        operations["read"] = {"status": "ok", "via": "extract_document"}
        validation = call("validate_artifact", {"artifact": source})
        operations["validate"] = {"status": "ok", "checks": validation["checks"]}
        same = call("compare_documents", {"left": source, "right": source})
        operations["compare"] = {"status": "ok", "equal": same["equal"]}
        primary = source
        if fmt in {"xlsx", "pptx", "pdf"}:
            operations["modify"] = {
                "status": "not_run",
                "reason": f"{fmt} mutation has no preview-proven approved route",
            }
        else:
            modified = coordinate(fmt, source, PATCHES[fmt])
            primary = modified
            operations["modify"] = {
                "status": "approved",
                "artifact": modified["content_hash"],
            }
            changed = call("compare_documents", {"left": source, "right": modified})
            if changed["equal"]:
                raise AssertionError(f"{fmt} modification made no change")
        rendered = call("render_artifact", {"artifact": primary}, refusal=True)
        render_error = cast(dict[str, object], rendered["error"])
        refusals.append({"format": fmt, "operation": "render", **render_error})
        primary_path = Path(primary["uri"])
        final_text = extracted_text(call("extract_document", {"source": primary}))
        _ = call("validate_artifact", {"artifact": primary})
        receipts = {
            receipt(Path(item["uri"]))["path"]: receipt(Path(item["uri"]))
            for item in (created, source, primary)
        }
        evidence[fmt] = {
            "capabilities": by_format[fmt]["capabilities"], "fixture_creation": fixture_kind,
            "operations": operations, "source_sha256_before": before,
            "source_sha256_after": sha256(source_path), "artifact_hashes": [r["sha256"] for r in receipts.values()],
            "artifacts": list(receipts.values()), "primary_artifact": str(primary_path.resolve()),
            "reopen_validation": reopen(primary_path, fmt),
            "expected_content_match": "Dogfood" in final_text,
        }
    ok = all(
        item["expected_content_match"] is True
        and item["source_sha256_before"] == item["source_sha256_after"]
        for item in evidence.values()
    )
    return {
        "ok": ok, "jail": str(jail), "formats": evidence,
        "expected_refusals": refusals,
        "cleanup_receipt": {"temporary_paths_removed": [],
                            "temporary_paths_remaining": [],
                            "artifacts_retained": True},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    _ = parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        report: dict[str, object] = run(cast(Path, args.output_dir))
    except (
        AssertionError,
        DocumentError,
        ImportError,
        LookupError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        report = {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ok"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
