"""Bounded artifact-style projection assembly for extracted document items."""

from __future__ import annotations

import hashlib
import json
from typing import cast

from .errors import DocumentError, DocumentErrorCode
from .service_types import (
    ExtractedItem,
    ExtractedNode,
    ExtractedSpan,
    ExtractionResult,
    FeatureSupport,
    Truncation,
)

MAX_EXTRACTED_SPANS = 10_000
MAX_EXTRACTED_NODES = 10_000
MAX_TEXT_BYTES = 1_000_000


class _TruncationStatus(dict[str, object]):
    """JSON object with legacy truth semantics for the TXT converter."""

    def __bool__(self) -> bool:
        return self.get("truncated") is True


def _limit(name: str, value: object, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "extract",
            f"{name} must be an integer between 1 and {maximum}",
        )
    return value


def validate_limits(
    max_spans: object, max_nodes: object, max_text_bytes: object
) -> tuple[int, int, int]:
    return (
        _limit("max_spans", max_spans, MAX_EXTRACTED_SPANS),
        _limit("max_nodes", max_nodes, MAX_EXTRACTED_NODES),
        _limit("max_text_bytes", max_text_bytes, MAX_TEXT_BYTES),
    )


def _text_prefix(text: str, byte_limit: int) -> str:
    if len(text.encode("utf-8")) <= byte_limit:
        return text
    return text.encode("utf-8")[:byte_limit].decode("utf-8", errors="ignore")


def _node_id(digest: str, item: ExtractedItem, order: int) -> str:
    identity = json.dumps(
        [digest, item["kind"], item["locator"], order],
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _feature_support(format_name: str) -> dict[str, FeatureSupport]:
    reason = (
        f"{format_name} semantic extraction is unsupported; no node is fabricated"
    )
    return {
        name: {"state": "unsupported", "reason": reason}
        for name in ("tables", "forms", "images", "comments", "fields")
    }


def build_extraction(
    items: list[ExtractedItem],
    format_name: str,
    digest: str,
    *,
    projection: str,
    max_spans: object,
    max_nodes: object,
    max_text_bytes: object,
) -> ExtractionResult:
    if projection != "text":
        raise DocumentError(
            DocumentErrorCode.INVALID_INPUT,
            "extract",
            "only the text projection is supported",
        )
    span_limit, node_limit, byte_limit = validate_limits(
        max_spans, max_nodes, max_text_bytes
    )
    spans: list[ExtractedSpan] = []
    nodes: list[ExtractedNode] = []
    text_parts: list[str] = []
    used_bytes = 0
    reasons: list[str] = []
    for order, item in enumerate(items, 1):
        if len(spans) >= span_limit:
            reasons.append("max_spans")
            break
        if len(nodes) >= node_limit:
            reasons.append("max_nodes")
            break
        separator_bytes = 1 if text_parts else 0
        remaining = byte_limit - used_bytes - separator_bytes
        if remaining <= 0:
            reasons.append("max_text_bytes")
            break
        text = _text_prefix(item["text"], remaining)
        if not text and item["text"]:
            reasons.append("max_text_bytes")
            break
        locator = {"document": f"sha256:{digest}", **item["locator"]}
        spans.append(
            {
                "text": text,
                "source_sha256": digest,
                "source_locator": locator,
                "method": item["method"],
            }
        )
        nodes.append(
            {
                "id": _node_id(digest, item, order),
                "kind": item["kind"],
                "text": text,
                "order": order,
                "source_locator": locator,
            }
        )
        text_parts.append(text)
        used_bytes += separator_bytes + len(text.encode("utf-8"))
        if text != item["text"]:
            reasons.append("max_text_bytes")
            break
    truncation = cast(
        "Truncation",
        cast(
            "object",
            _TruncationStatus(truncated=bool(reasons), reasons=reasons),
        ),
    )
    return {
        "source": {"sha256": digest, "locator": f"sha256:{digest}"},
        "spans": spans,
        "nodes": nodes,
        "text": "\n".join(text_parts),
        "projection": projection,
        "limits": {
            "max_spans": span_limit,
            "max_nodes": node_limit,
            "max_text_bytes": byte_limit,
        },
        "truncation": truncation,
        "unsupported": _feature_support(format_name),
    }
