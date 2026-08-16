"""Offline, real-document dogfood for the registered Office Work OS tools."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from birkin.office.conversion_audit import LOSS_CATEGORIES
from birkin.tools import build_registry
from birkin.tools._types import ToolContext
from script.qa.office_dogfood_fixtures import (
    artifact,
    docx_fixture,
    extracted_text,
    hwpx_fixture,
    receipt,
    reopen,
    sha256,
    zip_fixture,
)

FORMATS = ("docx", "xlsx", "pptx", "pdf", "hwpx")
LOSS_BUDGET = {category: 100 for category in LOSS_CATEGORIES}
CONTENT: dict[str, dict[str, object]] = {
    "docx": {"paragraphs": ["Dogfood DOCX evidence", "PLACEHOLDER"]},
    "xlsx": {"sheets": [{"name": "Evidence", "rows": [["Dogfood XLSX evidence"], [1]]}]},
    "pptx": {"slides": [{"title": "Dogfood PPTX evidence", "body": "PLACEHOLDER"}]},
    "pdf": {"paragraphs": ["Dogfood PDF evidence"]},
}
PATCHES: dict[str, dict[str, object]] = {
    "docx": {"field": "customer", "value": "Dogfood DOCX modified"},
    "xlsx": {"cell": "A2", "value": 42},
    "pptx": {"placeholder_idx": 1, "value": "Dogfood PPTX modified"},
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
            created = cast(dict[str, str], call("create_document", {
                "format": "hwpx", "content": {"bindings": {"customer": "Dogfood HWPX created"}},
                "output_name": "created-hwpx.hwpx", "template": source,
            })["draft_artifact"])
        else:
            created = cast(dict[str, str], call("create_document", {
                "format": fmt, "content": CONTENT[fmt], "output_name": f"created-{fmt}.{fmt}",
            })["draft_artifact"])
            created_path = Path(created["uri"])
            if fmt == "docx":
                source_path = sources / "source.docx"
                docx_fixture(created_path, source_path)
                source = artifact(source_path)
                fixture_kind = "deterministic_derived_fixture"
            elif fmt in {"xlsx", "pptx"}:
                source_path = sources / f"source.{fmt}"
                replacement = None
                if fmt == "xlsx":
                    replacement = (
                        "xl/worksheets/sheet1.xml", b'<c r="A2" t="n">', b'<c r="A2">'
                    )
                zip_fixture(created_path, source_path, replacement)
                source = artifact(source_path)
                fixture_kind = "deterministic_normalized_fixture"
            else:
                source = created
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
        converted = cast(dict[str, str], call("convert_document", {
            "source": source, "target_format": "txt",
            "output_name": f"converted-{fmt}.txt", "loss_budget": LOSS_BUDGET,
        })["draft_artifact"])
        operations["convert"] = {"status": "ok", "artifact": converted["content_hash"]}
        primary = source
        if fmt == "pdf":
            refused = call("apply_document_patch", {
                "base": source, "patch": {"operations": [{"value": "blocked"}]},
                "expected_source_sha256": before, "output_name": "modified-pdf.pdf", "dry_run": False,
            }, refusal=True)
            error = cast(dict[str, object], refused["error"])
            refusals.append({"format": fmt, "operation": "modify", **error})
            operations["modify"] = {"status": "expected_refusal", "error": error}
        else:
            modified = cast(dict[str, str], call("apply_document_patch", {
                "base": source, "patch": {"operations": [PATCHES[fmt]]},
                "expected_source_sha256": before, "output_name": f"modified-{fmt}.{fmt}", "dry_run": False,
            })["draft_artifact"])
            primary = modified
            operations["modify"] = {"status": "ok", "artifact": modified["content_hash"]}
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
            for item in (created, source, primary, converted)
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
