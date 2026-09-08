"""Bounded mail reading, local drafts, and approval-bound sending."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import config, store
from .m365_graph import GraphClient, GraphError, GraphUncertainError, graph_client
from .m365_connection import verify_approval_identity
from .office.artifact_serialization import canonical_json

ACTIONS = frozenset({"new", "reply", "reply_all", "forward"})
REMOTE_DRAFT_RESPONSE_LIMIT = 5 * 1024 * 1024


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
        digest = str(raw.get("content_hash", ""))
        encoded = raw.get("content_bytes")
        if isinstance(encoded, str):
            if len(encoded) > 4 * 1024 * 1024 + 16:
                raise ValueError("attachments exceed the 3 MiB draft limit")
            try:
                content = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ValueError("attachment bytes are invalid") from exc
            name = str(raw.get("name", ""))
        else:
            path = Path(str(raw.get("uri", ""))).resolve(strict=True)
            if not path.is_file() or not path.is_relative_to(root):
                raise ValueError("attachment must be a regular file inside BIRKIN_HOME")
            with path.open("rb") as stream:
                content = stream.read(3 * 1024 * 1024 - total + 1)
            name = str(raw.get("name") or path.name)
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("attachment hash mismatch")
        total += len(content)
        if total > 3 * 1024 * 1024:
            raise ValueError("attachments exceed the 3 MiB draft limit")
        result.append({"name": name, "content_hash": digest, "content_bytes": base64.b64encode(content).decode("ascii")})
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
    source_etag = payload.get("source_etag")
    if action != "new" and (not isinstance(source_etag, str) or not source_etag):
        raise ValueError("reply, reply_all, and forward require source_etag")
    draft: dict[str, object] = {
        "id": uuid.uuid4().hex,
        "action": action,
        "source_message_id": source_id if isinstance(source_id, str) else None,
        "source_etag": source_etag,
        "from_account": payload.get("from_account"),
        "to": _addresses(payload.get("to", []), "to"),
        "cc": _addresses(payload.get("cc", []), "cc"),
        "subject": str(payload.get("subject", "")).strip(),
        "body": str(payload.get("body", "")),
        "attachments": _attachments(payload.get("attachments")),
        "connection_identity": payload.get("connection_identity"),
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
        "bccRecipients": [],
    }
    if include_attachments:
        message["attachments"] = [
            {"@odata.type": "#microsoft.graph.fileAttachment", "name": item["name"], "contentBytes": item["content_bytes"]}
            for item in draft["attachments"] if isinstance(item, dict)
        ]
    return message


def _remote_draft(graph: GraphClient, remote_id: str, *, sent: bool = False) -> dict[str, Any]:
    selected = "id,isDraft,sentDateTime,subject,body,toRecipients,ccRecipients,bccRecipients" if sent else "id,isDraft,subject,body,toRecipients,ccRecipients,bccRecipients"
    path = f"/me/messages/{quote(remote_id, safe='')}?$select={selected}&$expand=attachments"
    if isinstance(graph, GraphClient):
        return graph.request("GET", path, response_limit=REMOTE_DRAFT_RESPONSE_LIMIT)
    return graph.request("GET", path)


def _require_source_version(graph: GraphClient, draft: Mapping[str, object]) -> None:
    source_id = str(draft["source_message_id"])
    source = graph.request("GET", f"/me/messages/{quote(source_id, safe='')}?$select=id,@odata.etag")
    if source.get("id") != source_id or source.get("@odata.etag") != draft.get("source_etag"):
        raise ValueError("원본 메일이 변경되었습니다. 새 검토를 만들어 주세요")


def _clear_inherited_attachments(graph: GraphClient, remote_id: str) -> None:
    result = graph.request("GET", f"/me/messages/{quote(remote_id, safe='')}?$select=id&$expand=attachments($select=id)")
    attachments = result.get("attachments", [])
    if not isinstance(attachments, list):
        raise GraphError("원격 메일 초안의 첨부 목록이 올바르지 않습니다")
    for item in attachments:
        attachment_id = item.get("id") if isinstance(item, Mapping) else None
        if not isinstance(attachment_id, str) or not attachment_id:
            raise GraphError("원격 메일 초안의 첨부 ID가 올바르지 않습니다")
        graph.request("DELETE", f"/me/messages/{quote(remote_id, safe='')}/attachments/{quote(attachment_id, safe='')}")


def _remote_matches(draft: Mapping[str, object], remote: Mapping[str, object]) -> bool:
    def addresses(key: str) -> list[str] | None:
        values = remote.get(key)
        if not isinstance(values, list):
            return None
        result: list[str] = []
        for item in values:
            address = item.get("emailAddress") if isinstance(item, Mapping) else None
            value = address.get("address") if isinstance(address, Mapping) else None
            if not isinstance(value, str) or not value:
                return None
            result.append(value.casefold())
        return result

    body = remote.get("body")
    attachments = remote.get("attachments")
    remote_files: list[tuple[str, str]] = []
    if "attachments@odata.nextLink" in remote or not isinstance(attachments, list):
        return False
    for item in attachments:
        if (
            not isinstance(item, Mapping)
            or item.get("@odata.type") != "#microsoft.graph.fileAttachment"
            or not isinstance(item.get("contentBytes"), str)
        ):
            return False
        try:
            content = base64.b64decode(item["contentBytes"], validate=True)
        except ValueError:
            return False
        remote_files.append((str(item.get("name", "")), hashlib.sha256(content).hexdigest()))
    expected_files = {(str(item["name"]), str(item["content_hash"])) for item in draft["attachments"] if isinstance(item, Mapping)}
    return (
        remote.get("subject") == draft["subject"]
        and isinstance(body, Mapping)
        and str(body.get("contentType", "")).casefold() == "text"
        and body.get("content") == draft["body"]
        and addresses("toRecipients") == [str(item).casefold() for item in draft["to"]]
        and addresses("ccRecipients") == [str(item).casefold() for item in draft["cc"]]
        and addresses("bccRecipients") == []
        and len(remote_files) == len(expected_files)
        and set(remote_files) == expected_files
    )


def _observed_state(observed: Mapping[str, object]) -> str | None:
    if observed.get("isDraft") is not False:
        return None
    sent_at = observed.get("sentDateTime")
    if not isinstance(sent_at, str) or not sent_at.strip():
        return "observed_non_draft"
    try:
        parsed = datetime.fromisoformat(sent_at.replace("Z", "+00:00"))
    except ValueError:
        return "observed_non_draft"
    if parsed.year == 1 or parsed.utcoffset() is None:
        return "observed_non_draft"
    return "submitted"


def _attempt_send(
    graph: GraphClient,
    remote_id: str,
    draft: Mapping[str, object],
    receipt: dict[str, Any],
    receipts: dict[str, Any],
    receipt_key: str,
) -> None:
    receipt["state"] = "send_attempted"
    receipts[receipt_key] = receipt
    store._write_json(config.mail_receipts_path(), receipts)
    try:
        _ = graph.request("POST", f"/me/messages/{quote(remote_id, safe='')}/send")
        receipt["state"] = "accepted"
        receipts[receipt_key] = receipt
        store._write_json(config.mail_receipts_path(), receipts)
    except GraphUncertainError:
        receipt["state"] = "unknown"
    try:
        observed = _remote_draft(graph, remote_id, sent=True)
    except GraphError:
        return
    observed_state = _observed_state(observed)
    if observed_state is not None:
        receipt["state"] = observed_state if _remote_matches(draft, observed) else "needs_review"


def _execute_approved_send(payload: dict[str, Any], client: GraphClient | None = None) -> str:
    draft = _load_bound(payload.get("draft_id", payload.get("id")), payload.get("content_sha256"))
    graph = client or graph_client()
    identity = verify_approval_identity(draft.get("connection_identity"), graph)
    if isinstance(draft.get("connection_identity"), Mapping) and str(draft["from_account"]).casefold() != str(identity["name"]).casefold():
        raise ValueError("approved sender does not match the executing Microsoft 365 account")
    receipts_raw = store._read_json(config.mail_receipts_path(), {})
    receipts = dict(receipts_raw) if isinstance(receipts_raw, dict) else {}
    receipt_key = str(draft["content_sha256"])
    existing = receipts.get(receipt_key)
    if isinstance(existing, dict) and isinstance(existing.get("remote_id"), str):
        remote_id = str(existing["remote_id"])
        if existing.get("state") == "sent":
            existing["state"] = "legacy_sent_unverified"
        try:
            observed = _remote_draft(graph, remote_id, sent=True)
        except GraphError:
            if existing.get("state") not in {"accepted", "submitted"}:
                existing["state"] = "unknown"
            receipts[receipt_key] = existing
            store._write_json(config.mail_receipts_path(), receipts)
            return json.dumps(existing, ensure_ascii=False, sort_keys=True)
        observed_state = _observed_state(observed)
        if observed_state is not None:
            if not _remote_matches(draft, observed):
                existing["state"] = "needs_review"
                receipts[receipt_key] = existing
                store._write_json(config.mail_receipts_path(), receipts)
                raise ValueError("remote mail differs from the approved content")
            existing["state"] = observed_state
            receipts[receipt_key] = existing
            store._write_json(config.mail_receipts_path(), receipts)
            return json.dumps(existing, ensure_ascii=False, sort_keys=True)
        if existing.get("state") == "remote_draft_created" and observed.get("isDraft") is not True:
            existing["state"] = "needs_review"
            receipts[receipt_key] = existing
            store._write_json(config.mail_receipts_path(), receipts)
            return json.dumps(existing, ensure_ascii=False, sort_keys=True)
        if not _remote_matches(draft, observed):
            existing["state"] = "needs_review"
            receipts[receipt_key] = existing
            store._write_json(config.mail_receipts_path(), receipts)
            raise ValueError("remote mail draft changed; create a new review")
        if existing.get("state") == "remote_draft_created":
            _attempt_send(graph, remote_id, draft, existing, receipts, receipt_key)
            receipts[receipt_key] = existing
            store._write_json(config.mail_receipts_path(), receipts)
            return json.dumps(existing, ensure_ascii=False, sort_keys=True)
        # A durable attempt marker means this remote draft may already have
        # been accepted. Re-entry only observes it; it never sends again.
        if existing.get("state") == "send_attempted":
            existing["state"] = "unknown"
        receipts[receipt_key] = existing
        store._write_json(config.mail_receipts_path(), receipts)
        return json.dumps(existing, ensure_ascii=False, sort_keys=True)
    action, source = draft["action"], draft.get("source_message_id")
    if action == "new":
        remote = graph.request("POST", "/me/messages", _message(draft, include_attachments=True))
    else:
        _require_source_version(graph, draft)
        suffix = {"reply": "createReply", "reply_all": "createReplyAll", "forward": "createForward"}[str(action)]
        remote = graph.request("POST", f"/me/messages/{quote(str(source), safe='')}/{suffix}")
        remote_id = remote.get("id")
        if not isinstance(remote_id, str):
            raise GraphError("Microsoft Graph returned no draft id")
        _clear_inherited_attachments(graph, remote_id)
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
    observed = _remote_draft(graph, remote_id)
    if observed.get("isDraft") is not True or not _remote_matches(draft, observed):
        receipt["state"] = "needs_review"
        receipts[receipt_key] = receipt
        store._write_json(config.mail_receipts_path(), receipts)
        raise ValueError("remote mail draft changed; create a new review")
    _attempt_send(graph, remote_id, draft, receipt, receipts, receipt_key)
    receipts[receipt_key] = receipt
    store._write_json(config.mail_receipts_path(), receipts)
    return json.dumps(receipt, ensure_ascii=False, sort_keys=True)


def execute_approved_send(payload: dict[str, Any], client: GraphClient | None = None) -> str:
    with store.file_lock(config.mail_receipts_path()):
        return _execute_approved_send(payload, client)


def reconcile_approved_send(payload: dict[str, Any], client: GraphClient | None = None) -> str:
    """Observe one approval-bound remote draft without creating or sending it."""
    draft = _load_bound(payload.get("draft_id", payload.get("id")), payload.get("content_sha256"))
    graph = client or graph_client()
    identity = verify_approval_identity(draft.get("connection_identity"), graph)
    if isinstance(draft.get("connection_identity"), Mapping) and str(draft["from_account"]).casefold() != str(identity["name"]).casefold():
        raise ValueError("approved sender does not match the executing Microsoft 365 account")
    with store.file_lock(config.mail_receipts_path()):
        raw = store._read_json(config.mail_receipts_path(), {})
        receipts = dict(raw) if isinstance(raw, dict) else {}
        key = str(draft["content_sha256"])
        receipt = receipts.get(key)
        if not isinstance(receipt, dict) or not isinstance(receipt.get("remote_id"), str):
            raise ValueError("mail send attempt has no durable remote id")
        if receipt.get("state") == "sent":
            receipt["state"] = "legacy_sent_unverified"
        remote_id = str(receipt["remote_id"])
        try:
            observed = _remote_draft(graph, remote_id, sent=True)
        except GraphError:
            if receipt.get("state") not in {"accepted", "submitted"}:
                receipt["state"] = "unknown"
        else:
            observed_state = _observed_state(observed)
            if observed_state is not None:
                receipt["state"] = observed_state if _remote_matches(draft, observed) else "needs_review"
            elif receipt.get("state") == "legacy_sent_unverified":
                pass
            elif _remote_matches(draft, observed):
                if receipt.get("state") == "send_attempted":
                    receipt["state"] = "unknown"
            else:
                receipt["state"] = "needs_review"
        receipts[key] = receipt
        store._write_json(config.mail_receipts_path(), receipts)
        return json.dumps(receipt, ensure_ascii=False, sort_keys=True)


__all__ = ["create_local_draft", "execute_approved_send", "get_local_draft", "list_messages", "reconcile_approved_send"]
