"""Version-bound Microsoft 365 review handoff and local comments."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from . import config, store
from .m365_graph import GraphClient, graph_client
from .m365_connection import current_verified_identity, verify_approval_identity
from .office.artifact_serialization import canonical_json


def _read() -> dict[str, dict[str, object]]:
    raw = store._read_json(config.team_reviews_path(), {})
    return {str(key): dict(value) for key, value in raw.items() if isinstance(value, dict)} if isinstance(raw, dict) else {}


def _write(records: Mapping[str, object]) -> None:
    store._write_json(config.team_reviews_path(), dict(records))


def create_handoff(payload: Mapping[str, object]) -> dict[str, object]:
    reviewers = payload.get("reviewers")
    if isinstance(reviewers, (str, bytes)) or not isinstance(reviewers, Sequence) or not reviewers:
        raise ValueError("reviewers must be a non-empty array")
    reviewer_list = sorted({str(item).strip().casefold() for item in reviewers})
    if any("@" not in item for item in reviewer_list):
        raise ValueError("reviewer must be an email address")
    role = payload.get("role", "read")
    if role not in {"read", "write"}:
        raise ValueError("role must be read or write")
    record: dict[str, object] = {
        "id": uuid.uuid4().hex,
        "drive_item_id": str(payload.get("drive_item_id", "")),
        "source_etag": str(payload.get("source_etag", "")),
        "source_name": str(payload.get("source_name", "")),
        "proposer": str(payload.get("proposer", "")).casefold(),
        "reviewers": reviewer_list,
        "role": role,
        "message": str(payload.get("message", ""))[:2000],
        "status": "draft",
        "comments": [],
        "connection_identity": payload.get("connection_identity"),
    }
    if not all(record[key] for key in ("drive_item_id", "source_etag", "source_name", "proposer")):
        raise ValueError("drive_item_id, source_etag, source_name, and proposer are required")
    record["content_sha256"] = hashlib.sha256(canonical_json(record).encode()).hexdigest()
    with store.file_lock(config.team_reviews_path()):
        records = _read()
        records[str(record["id"])] = record
        _write(records)
    return record


def get_handoff(review_id: object, digest: object) -> dict[str, object]:
    record = _read().get(str(review_id))
    if record is None or record.get("content_sha256") != digest:
        raise ValueError("review handoff is missing or changed")
    copy = dict(record)
    expected = copy.pop("content_sha256")
    if hashlib.sha256(canonical_json(copy).encode()).hexdigest() != expected:
        raise ValueError("review handoff changed; create a new review")
    return record


def _current(item_id: str, client: GraphClient) -> dict[str, Any]:
    return client.request("GET", f"/me/drive/items/{quote(item_id, safe='')}?$select=id,name,eTag")


def execute_share(payload: dict[str, Any], *, approval_id: str | None, client: GraphClient | None = None) -> str:
    record = get_handoff(payload.get("review_id", payload.get("id")), payload.get("content_sha256"))
    graph = client or graph_client()
    verify_approval_identity(record.get("connection_identity"), graph)
    current = _current(str(record["drive_item_id"]), graph)
    if current.get("eTag") != record["source_etag"]:
        raise ValueError("source document version changed; create a new review")
    result = graph.request("POST", f"/me/drive/items/{quote(str(record['drive_item_id']), safe='')}/invite", {
        "recipients": [{"email": reviewer} for reviewer in record["reviewers"]],
        "message": record["message"], "requireSignIn": True, "sendInvitation": True, "roles": [record["role"]],
    })
    from . import store as pending_store

    pending = pending_store.get_pending(approval_id) if approval_id else None
    record.update({
        "status": "shared", "executor": pending.get("approved_by") if pending else None,
        "shared_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "permissions": result.get("value", []),
    })
    record["content_sha256"] = hashlib.sha256(canonical_json({key: value for key, value in record.items() if key != "content_sha256"}).encode()).hexdigest()
    with store.file_lock(config.team_reviews_path()):
        records = _read()
        records[str(record["id"])] = record
        _write(records)
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


def add_comment(payload: Mapping[str, object], *, client: GraphClient | None = None) -> dict[str, object]:
    review_id, text = str(payload.get("review_id", "")), str(payload.get("text", "")).strip()
    with store.file_lock(config.team_reviews_path()):
        records = _read()
        record = records.get(review_id)
        graph = client or graph_client(allow_unverified=True)
        actor = str(current_verified_identity(graph)["name"]).casefold()
        members = {str(member).casefold() for member in [*record.get("reviewers", []), record.get("proposer")]} if record else set()
        if record is None or actor not in members:
            raise PermissionError("actor cannot access this review")
        if not text:
            raise ValueError("comment text is required")
        current = _current(str(record["drive_item_id"]), graph)
        if current.get("eTag") != record["source_etag"]:
            raise ValueError("source document version changed; comment targets an older version")
        comments = list(record.get("comments", []))
        comment = {"id": uuid.uuid4().hex, "actor": actor, "text": text, "source_etag": record["source_etag"], "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        comments.append(comment)
        record["comments"] = comments
        record["content_sha256"] = hashlib.sha256(canonical_json({key: value for key, value in record.items() if key != "content_sha256"}).encode()).hexdigest()
        _write(records)
    return comment


def list_review(review_id: object, *, client: GraphClient | None = None) -> dict[str, object]:
    record = _read().get(str(review_id))
    graph = client or graph_client(allow_unverified=True)
    actor = str(current_verified_identity(graph)["name"]).casefold()
    members = {str(member).casefold() for member in [*record.get("reviewers", []), record.get("proposer")]} if record else set()
    if record is None or actor not in members:
        raise PermissionError("actor cannot access this review")
    return record


__all__ = ["add_comment", "create_handoff", "execute_share", "get_handoff", "list_review"]
