"""Public typed worker request API and approval verification."""

from __future__ import annotations

import hashlib
import hmac

from .worker_request_boundary import object_fields
from .worker_request_models import (
    DaedalusCreate,
    DaedalusNote,
    DaedalusProfile,
    DaedalusRefresh,
    DaedalusShow,
    HarnessAction,
    HarnessRequest,
    HarnessScope,
    JsonObject,
    JsonValue,
    MoiraiList,
    MoiraiResume,
    MoiraiRun,
    MoiraiStatus,
    MorpheusRun,
    NeurosisRequest,
    OdysseyRequest,
    Resolution,
    WorkerRequest,
    WorkerRequestError,
    action_name,
    approval_payload,
    canonical,
    request_data,
    worker_name,
)
from .worker_request_parser import parse_request


def parse(value: object) -> WorkerRequest:
    return parse_request(value)


def approved_request(payload: object) -> WorkerRequest:
    raw = object_fields(payload, label="worker approval payload")
    if set(raw) != {"version", "request", "digest"}:
        raise WorkerRequestError("invalid worker approval payload fields")
    if raw.get("version") != 1:
        raise WorkerRequestError("unsupported worker approval version")
    request = parse(raw.get("request"))
    digest = raw.get("digest")
    if not isinstance(digest, str) or not hmac.compare_digest(
        hashlib.sha256(canonical(request)).hexdigest(), digest
    ):
        raise WorkerRequestError("worker approval digest mismatch")
    return request


__all__ = [
    "DaedalusCreate",
    "DaedalusNote",
    "DaedalusProfile",
    "DaedalusRefresh",
    "DaedalusShow",
    "HarnessAction",
    "HarnessRequest",
    "HarnessScope",
    "JsonObject",
    "JsonValue",
    "MoiraiList",
    "MoiraiResume",
    "MoiraiRun",
    "MoiraiStatus",
    "MorpheusRun",
    "NeurosisRequest",
    "OdysseyRequest",
    "Resolution",
    "WorkerRequest",
    "WorkerRequestError",
    "action_name",
    "approval_payload",
    "approved_request",
    "canonical",
    "parse",
    "request_data",
    "worker_name",
]
