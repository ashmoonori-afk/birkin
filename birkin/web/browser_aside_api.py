"""HTTP-neutral request adapter for Native Browser Aside."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import cast
from urllib.parse import parse_qs, urlsplit

from birkin.browser_aside_control import BrowserControlConflict
from birkin.browser_aside_errors import BrowserAsideError
from birkin.web.browser_aside_workspace import BrowserApiWorkspace

MAX_BROWSER_BODY_BYTES = 4_096


@dataclass(frozen=True, slots=True)
class BrowserApiResponse:
    status: int
    payload: dict[str, object] | bytes | None
    content_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)


def is_browser_path(raw_path: str) -> bool:
    return urlsplit(raw_path).path.startswith("/api/browser-aside/")


def get(
    raw_path: str,
    *,
    actor_id: str,
    workspace: BrowserApiWorkspace,
) -> BrowserApiResponse:
    del actor_id
    parsed = urlsplit(raw_path)
    try:
        if parsed.path == "/api/browser-aside/status":
            return BrowserApiResponse(
                200,
                workspace.status(),
            )
        if parsed.path == "/api/browser-aside/frame":
            query = parse_qs(parsed.query, strict_parsing=False)
            generation = _optional_int(query, "generation")
            if generation is None:
                raise ValueError("generation is required")
            after = _optional_int(query, "after")
            frame, status = workspace.frame(generation=generation)
            revision = cast(int, status["frame_revision"])
            if after is not None and after >= revision:
                return BrowserApiResponse(204, None)
            headers = {
                "Cache-Control": "no-store",
                "X-Birkin-Browser-Session": cast(
                    str,
                    status["browser_session_id"],
                ),
                "X-Birkin-Browser-Generation": str(
                    status["browser_generation"]
                ),
                "X-Birkin-Browser-Revision": str(
                    status["browser_revision"]
                ),
                "X-Birkin-Frame-Revision": str(revision),
                "X-Birkin-Frame-Digest": frame.digest,
                "X-Birkin-Frame-Ref": frame.ref,
            }
            return BrowserApiResponse(
                200,
                frame.content,
                "image/jpeg",
                headers,
            )
        return _not_found()
    except BrowserAsideError as exc:
        return _error(exc)
    except ValueError:
        return _typed_error(
            400,
            "invalid_query",
            "Browser request query is invalid.",
        )


def post(
    raw_path: str,
    body: bytes,
    *,
    actor_id: str,
    workspace: BrowserApiWorkspace,
) -> BrowserApiResponse:
    parsed = urlsplit(raw_path)
    try:
        payload = _json_object(body)
        if parsed.path == "/api/browser-aside/session":
            _require_keys(payload, ())
            status, created = workspace.start(actor_id)
            return BrowserApiResponse(
                201 if created else 200,
                status,
            )
        if parsed.path == "/api/browser-aside/navigate":
            _require_keys(
                payload,
                (
                    "url",
                    "browser_generation",
                    "browser_revision",
                    "control_epoch",
                    "control_sequence",
                ),
            )
            url = payload["url"]
            if not isinstance(url, str):
                raise ValueError("url must be a string")
            return BrowserApiResponse(
                200,
                workspace.navigate(url, payload, actor_id=actor_id),
            )
        return _not_found()
    except BrowserControlConflict:
        return _typed_error(
            409,
            "control_owner_conflict",
            "Browser control is owned by another client.",
        )
    except BrowserAsideError as exc:
        return _error(exc)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        return _typed_error(
            400,
            "invalid_request",
            "Browser request body is invalid.",
        )


def delete(
    raw_path: str,
    *,
    actor_id: str,
    workspace: BrowserApiWorkspace,
) -> BrowserApiResponse:
    parsed = urlsplit(raw_path)
    if parsed.path != "/api/browser-aside/session":
        return _not_found()
    try:
        query = parse_qs(parsed.query, strict_parsing=False)
        payload: dict[str, object] = {
            "browser_generation": _optional_int(
                query,
                "generation",
            ),
            "browser_revision": _optional_int(
                query,
                "revision",
            ),
            "control_epoch": _optional_int(
                query,
                "control_epoch",
            ),
            "control_sequence": _optional_int(
                query,
                "control_sequence",
            ),
        }
        return BrowserApiResponse(
            200,
            workspace.close(payload, actor_id=actor_id),
        )
    except BrowserAsideError as exc:
        return _error(exc)
    except BrowserControlConflict:
        return _typed_error(
            409,
            "control_owner_conflict",
            "Browser control is stale or not owned.",
        )
    except ValueError:
        return _typed_error(
            400,
            "invalid_query",
            "Browser request query is invalid.",
        )


def close_service(
    *,
    workspace: BrowserApiWorkspace,
) -> dict[str, object]:
    return workspace.force_close()


def _json_object(body: bytes) -> dict[str, object]:
    if len(body) > MAX_BROWSER_BODY_BYTES:
        raise ValueError("browser request is too large")
    raw = cast(object, json.loads(body.decode("utf-8")))
    if not isinstance(raw, dict):
        raise TypeError("browser request must be an object")
    mapping = cast(dict[object, object], raw)
    if not all(isinstance(key, str) for key in mapping):
        raise ValueError("browser request keys must be strings")
    return cast(dict[str, object], mapping)


def _require_keys(
    payload: dict[str, object],
    keys: tuple[str, ...],
) -> None:
    if set(payload) != set(keys):
        raise ValueError("browser request keys do not match the schema")


def _optional_int(
    query: dict[str, list[str]],
    name: str,
) -> int | None:
    values = query.get(name)
    if values is None:
        return None
    if len(values) != 1:
        raise ValueError(f"{name} must occur once")
    value = int(values[0])
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _error(error: BrowserAsideError) -> BrowserApiResponse:
    return _typed_error(error.status, error.code, error.message)


def _typed_error(
    status: int,
    code: str,
    message: str,
) -> BrowserApiResponse:
    return BrowserApiResponse(
        status,
        {"error": {"code": code, "message": message}},
    )


def _not_found() -> BrowserApiResponse:
    return _typed_error(404, "not_found", "Browser endpoint not found.")
