"""Authenticated OneDrive imports with locally bound provenance."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import config, store
from .m365_connection import current_verified_identity
from .m365_graph import GraphError, graph_client
from .office.coordinator_data import canonical_office_home
from .office.service import DocumentService

MAX_IMPORT_BYTES = 50 * 1024 * 1024
SUPPORTED_SUFFIXES = frozenset({".docx", ".xlsx", ".pptx", ".pdf", ".hwpx"})


def _records() -> dict[str, dict[str, object]]:
    raw = store._read_json(config.m365_imports_path(), {})
    return {str(key): dict(value) for key, value in raw.items() if isinstance(value, Mapping)} if isinstance(raw, Mapping) else {}


def _metadata(client: Any, item_id: str) -> dict[str, Any]:
    if not isinstance(item_id, str) or item_id != item_id.strip() or not item_id or len(item_id) > 512:
        raise ValueError("Drive 항목 ID는 비어 있지 않은 문자열이어야 합니다")
    result = client.request("GET", f"/me/drive/items/{quote(item_id, safe='')}?$select=id,name,eTag,size,file")
    if (
        result.get("id") != item_id
        or not isinstance(result.get("name"), str)
        or not result["name"].strip()
        or not isinstance(result.get("eTag"), str)
        or not result["eTag"].strip()
        or not isinstance(result.get("file"), Mapping)
    ):
        raise GraphError("Microsoft Graph의 Drive 항목 정보가 올바르지 않습니다")
    size = result.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > MAX_IMPORT_BYTES:
        raise GraphError("Microsoft 365 문서가 가져오기 크기 제한을 초과했습니다")
    return result


def import_document(drive_item_id: str, *, client: Any | None = None, service: DocumentService | None = None) -> dict[str, object]:
    graph = client or graph_client(allow_unverified=True)
    identity = current_verified_identity(graph)
    item = _metadata(graph, drive_item_id)
    suffix = Path(str(item["name"])).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("지원하지 않는 Microsoft 365 문서 형식입니다")
    content = graph.download(f"/me/drive/items/{quote(drive_item_id, safe='')}/content", max_bytes=MAX_IMPORT_BYTES)
    if len(content) != item["size"]:
        raise GraphError("다운로드 중 Microsoft 365 문서가 변경되었습니다")
    confirmed = _metadata(graph, drive_item_id)
    if confirmed["eTag"] != item["eTag"] or confirmed["size"] != item["size"]:
        raise GraphError("다운로드 중 Microsoft 365 문서가 변경되었습니다")
    digest = hashlib.sha256(content).hexdigest()
    office = service or DocumentService(canonical_office_home())
    import_id = uuid.uuid4().hex
    stem = re.sub(r"[^\w.-]+", "_", Path(str(item["name"])).stem, flags=re.UNICODE).strip("._") or "document"
    output_name = f"{stem[:80]}-{import_id[:8]}{suffix}"
    staging = office.home / "m365-import.tmp"
    fd, raw_path = tempfile.mkstemp(prefix="download-", suffix=suffix, dir=staging if staging.is_dir() else office.home)
    path = Path(raw_path)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        imported = office.import_document(path, expected_sha256=digest, output_name=output_name)
    finally:
        path.unlink(missing_ok=True)
    artifact = imported["artifact"]
    record = {
        "import_id": import_id,
        "artifact": artifact,
        "account_id": identity["id"],
        "account_name": identity["name"],
        "connection_generation": identity["generation"],
        "tenant_id": identity["tenant_id"],
        "drive_item_id": drive_item_id,
        "imported_etag": item["eTag"],
        "content_sha256": digest,
        "remote_name": item["name"],
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with store.file_lock(config.m365_imports_path()):
        records = _records()
        records[import_id] = record
        store._write_json(config.m365_imports_path(), records)
    return {**imported, "provenance": record}


def resolve_source(source: Mapping[str, object], *, client: Any | None = None) -> dict[str, object]:
    import_id = source.get("import_id")
    if not isinstance(import_id, str) or not import_id:
        raise ValueError("연결 문서 검색에는 import_id가 필요합니다")
    record = _records().get(import_id)
    if record is None:
        raise ValueError("신뢰할 수 있는 Microsoft 365 가져오기 기록을 찾지 못했습니다")
    if "artifact" in source and source["artifact"] != record.get("artifact"):
        raise ValueError("검색 문서가 신뢰할 수 있는 가져오기 기록과 일치하지 않습니다")
    graph = client or graph_client(allow_unverified=True)
    identity = current_verified_identity(graph)
    if (
        identity.get("id") != record.get("account_id")
        or identity.get("generation") != record.get("connection_generation")
        or not isinstance(record.get("tenant_id"), str)
        or identity.get("tenant_id") != record.get("tenant_id")
    ):
        raise ValueError("문서를 가져온 뒤 Microsoft 365 계정이 변경되었습니다")
    item = _metadata(graph, str(record["drive_item_id"]))
    return {
        "access_granted": True,
        "artifact": record["artifact"],
        "version": record["imported_etag"],
        "current_version": item["eTag"],
        "label": record["remote_name"],
    }


__all__ = ["MAX_IMPORT_BYTES", "import_document", "resolve_source"]
