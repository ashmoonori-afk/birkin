"""Bounded mail reading, local drafts, and approval-bound sending."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import config, store
from .m365_graph import GraphClient, GraphError, GraphUncertainError, graph_client
from .office.artifact_serialization import canonical_json

ACTIONS = frozenset({"new", "reply", "reply_all", "forward"})


def list_messages(*, unread_only: bool = True, limit: int = 20, client: GraphClient | None = None) -> dict[str, object]:
    if isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    query = "$select=id,conversationId,sender,toRecipients,ccRecipients,subject,bodyPreview,receivedDateTime,importance,isRead,@odata.etag"
    if unread_only:
        query += "&$filter=isRead%20eq%20false"
    query += f"&$top={limit}"
    result = (client or graph_client()).request("GET", f"/me/messages?{query}")
    values = result.get("value", [])
    return {"messages": values if isinstance(values, list) else [], "source": "microsoft-graph", "bounded": True}


def _addresses(value: object, label: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be an array")
    result = []
    for item in value:
        if not isinstance(item, str) or "@" not in item or len(item) > 320:
            raise ValueError(f"{label} contains an invalid address")
        result.append(item.strip())
    return result


def _attachments(value: object) -> list[dict[str, str]]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) > 20:
        raise ValueError("attachments must be an array of at most 20 items")
    result = []
    total = 0
    root = config.birkin_home().resolve()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise ValueError("attachment must be an object")
        path = Path(str(raw.get("uri", ""))).resolve(strict=True)
        digest = str(raw.get("content_hash", ""))
        if not path.is_file() or not path.is_relative_to(root):
            raise ValueError("attachment must be a regular file inside BIRKIN_HOME")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("attachment hash mismatch")
        total += path.stat().st_size
        if total > 3 * 1024 * 1024:
            raise ValueError("attachments exceed the 3 MiB draft limit")
        result.append({"name": str(raw.get("name") or path.name), "uri": str(path), "content_hash": digest})
    return result


def _digest(draft: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(draft).encode()).hexdigest()


def create_local_draft(payload: Mapping[str, object]) -> dict[str, object]:
    action = payload.get("action")
    if action not in ACTIONS:
        raise ValueError("unsupported mail action")
    source_id = payload.get("source_message_id")
    if action != "new" and (not isinstance(source_id, str) or not source_id):
        raise ValueError("reply, reply_all, and forward require source_message_id")
    draft: dict[str, object] = {
        "id": uuid.uuid4().hex,
        "action": action,
        "source_message_id": source_id if isinstance(source_id, str) else None,
        "source_etag": payload.get("source_etag"),
        "from_account": payload.get("from_account"),
        "to": _addresses(payload.get("to", []), "to"),
        "cc": _addresses(payload.get("cc", []), "cc"),
        "subject": str(payload.get("subject", "")).strip(),
        "body": str(payload.get("body", "")),
        "attachments": _attachments(payload.get("attachments")),
    }
    if not draft["from_account"] or not draft["to"] or not draft["subject"] or not draft["body"]:
        raise ValueError("from_account, to, subject, and body are required")
    draft["content_sha256"] = _digest(draft)
    with store.file_lock(config.mail_drafts_path()):
        raw = store._read_json(config.mail_drafts_path(), {})
        drafts = dict(raw) if isinstance(raw, dict) else {}
        drafts[str(draft["id"])] = draft
        store._write_json(config.mail_drafts_path(), drafts)
    return draft


def _load_bound(draft_id: object, digest: object) -> dict[str, object]:
    raw = store._read_json(config.mail_drafts_path(), {})
    draft = raw.get(draft_id) if isinstance(raw, dict) and isinstance(draft_id, str) else None
    if not isinstance(draft, dict) or draft.get("content_sha256") != digest:
        raise ValueError("mail draft is missing or changed; create a new review")
    copy = dict(draft)
    stored_digest = copy.pop("content_sha256")
    if _digest(copy) != stored_digest:
        raise ValueError("mail draft content changed; create a new review")
    _ = _attachments(copy.get("attachments"))
    return draft


def get_local_draft(draft_id: object, digest: object) -> dict[str, object]:
    return dict(_load_bound(draft_id, digest))


def _recipients(addresses: object) -> list[dict[str, object]]:
    return [{"emailAddress": {"address": address}} for address in addresses if isinstance(address, str)]


def _message(draft: Mapping[str, object], *, include_attachments: bool) -> dict[str, object]:
    message: dict[str, object] = {
        "subject": draft["subject"],
        "body": {"contentType": "Text", "content": draft["body"]},
        "toRecipients": _recipients(draft["to"]),
        "ccRecipients": _recipients(draft["cc"]),
    }
    if include_attachments:
        message["attachments"] = [
            {"@odata.type": "#microsoft.graph.fileAttachment", "name": item["name"], "contentBytes": base64.b64encode(Path(item["uri"]).read_bytes()).decode("ascii")}
            for item in draft["attachments"] if isinstance(item, dict)
        ]
    return message


def execute_approved_send(payload: dict[str, Any], client: GraphClient | None = None) -> str:
    draft = _load_bound(payload.get("draft_id", payload.get("id")), payload.get("content_sha256"))
    graph = client or graph_client()
    receipts_raw = store._read_json(config.mail_receipts_path(), {})
    receipts = dict(receipts_raw) if isinstance(receipts_raw, dict) else {}
    receipt_key = str(draft["content_sha256"])
    existing = receipts.get(receipt_key)
    if isinstance(existing, dict) and isinstance(existing.get("remote_id"), str):
        if existing.get("state") == "sent":
            return json.dumps(existing, ensure_ascii=False, sort_keys=True)
        remote_id = str(existing["remote_id"])
        try:
            observed = graph.request("GET", f"/me/messages/{quote(remote_id, safe='')}?$select=id,isDraft,sentDateTime")
        except GraphError:
            existing["state"] = "unknown"
            receipts[receipt_key] = existing
            store._write_json(config.mail_receipts_path(), receipts)
            return json.dumps(existing, ensure_ascii=False, sort_keys=True)
        if observed.get("isDraft") is False:
            existing["state"] = "sent"
            receipts[receipt_key] = existing
            store._write_json(config.mail_receipts_path(), receipts)
            return json.dumps(existing, ensure_ascii=False, sort_keys=True)
        try:
            _ = graph.request("POST", f"/me/messages/{quote(remote_id, safe='')}/send")
            existing["state"] = "sent"
        except GraphUncertainError:
            existing["state"] = "unknown"
        receipts[receipt_key] = existing
        store._write_json(config.mail_receipts_path(), receipts)
        return json.dumps(existing, ensure_ascii=False, sort_keys=True)
    action, source = draft["action"], draft.get("source_message_id")
    if action == "new":
        remote = graph.request("POST", "/me/messages", _message(draft, include_attachments=True))
    else:
        suffix = {"reply": "createReply", "reply_all": "createReplyAll", "forward": "createForward"}[str(action)]
        remote = graph.request("POST", f"/me/messages/{quote(str(source), safe='')}/{suffix}")
        remote_id = remote.get("id")
        if not isinstance(remote_id, str):
            raise GraphError("Microsoft Graph returned no draft id")
        _ = graph.request("PATCH", f"/me/messages/{quote(remote_id, safe='')}", _message(draft, include_attachments=False))
        for item in draft["attachments"]:
            if isinstance(item, dict):
                _ = graph.request("POST", f"/me/messages/{quote(remote_id, safe='')}/attachments", _message({**draft, "attachments": [item]}, include_attachments=True)["attachments"][0])
    remote_id = remote.get("id")
    if not isinstance(remote_id, str):
        raise GraphError("Microsoft Graph returned no immutable draft id")
    receipt = {"draft_id": draft["id"], "content_sha256": draft["content_sha256"], "remote_id": remote_id, "state": "remote_draft_created"}
    receipts[receipt_key] = receipt
    store._write_json(config.mail_receipts_path(), receipts)
    try:
        _ = graph.request("POST", f"/me/messages/{quote(remote_id, safe='')}/send")
        receipt["state"] = "sent"
    except GraphUncertainError:
        try:
            observed = graph.request("GET", f"/me/messages/{quote(remote_id, safe='')}?$select=id,isDraft,sentDateTime")
        except GraphError:
            receipt["state"] = "unknown"
        else:
            receipt["state"] = "sent" if observed.get("isDraft") is False else "confirmed_draft"
    receipts[receipt_key] = receipt
    store._write_json(config.mail_receipts_path(), receipts)
    return json.dumps(receipt, ensure_ascii=False, sort_keys=True)


__all__ = ["create_local_draft", "execute_approved_send", "get_local_draft", "list_messages"]
