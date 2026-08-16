"""Idempotent, bounded action receipt storage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


def request_digest(request: dict[str, Any]) -> str:
    encoded = json.dumps(
        request,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredReceipt:
    request_digest: str
    response: dict[str, Any]


class ReceiptStore:
    def __init__(self) -> None:
        self._receipts: dict[tuple[str, str], StoredReceipt] = {}
        self._by_ref: dict[str, StoredReceipt] = {}

    def lookup(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        digest: str,
    ) -> dict[str, Any] | None:
        stored = self._receipts.get((session_id, idempotency_key))
        if stored is None:
            return None
        if stored.request_digest != digest:
            return {
                "ok": False,
                "status": "refused",
                "effect": "suspected_noop",
                "refusal_code": "idempotency_conflict",
                "mutation_dispatched": False,
            }
        return dict(stored.response)

    def record(
        self,
        *,
        session_id: str,
        idempotency_key: str,
        digest: str,
        response: dict[str, Any],
    ) -> None:
        self._receipts[(session_id, idempotency_key)] = StoredReceipt(
            request_digest=digest,
            response=dict(response),
        )
        ref = response.get("receipt_ref")
        if isinstance(ref, str):
            self._by_ref[ref] = StoredReceipt(
                request_digest=digest,
                response=dict(response),
            )

    def get(self, ref: str) -> StoredReceipt | None:
        return self._by_ref.get(ref)


def receipt_ref(response: dict[str, Any]) -> str:
    bounded = {
        key: value
        for key, value in response.items()
        if key not in {"receipt_ref", "text"}
    }
    encoded = json.dumps(
        bounded,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
