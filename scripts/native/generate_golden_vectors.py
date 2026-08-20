"""Generate cross-language golden vectors with the real Python native codec.

The macOS Swift package must decode exactly what Birkin's Python bridge emits,
so the fixtures the Swift tests consume are produced here by
``birkin.native.protocol.encode_frame`` itself rather than by a hand-written
transcription of the wire format.

Usage (from the repository root)::

    uv run python scripts/native/generate_golden_vectors.py
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from birkin.native.protocol import (
    MAX_FRAME_BYTES,
    MAX_JSON_DEPTH,
    NATIVE_PROTOCOL_NAME,
    NATIVE_PROTOCOL_VERSION,
    decode_frame,
    encode_frame,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = (
    REPO_ROOT
    / "macos"
    / "BirkinNativeApp"
    / "Tests"
    / "BirkinNativeProtocolTests"
    / "GoldenVectors"
    / "native-protocol-vectors.json"
)


def _envelope(
    kind: str,
    frame_id: str,
    body: dict[str, object],
    in_reply_to: str | None = None,
) -> dict[str, object]:
    return {
        "protocol": NATIVE_PROTOCOL_NAME,
        "protocol_version": NATIVE_PROTOCOL_VERSION,
        "kind": kind,
        "id": frame_id,
        "in_reply_to": in_reply_to,
        "body": body,
    }


def build_vectors() -> list[dict[str, object]]:
    """Return every named envelope the Swift package is expected to handle."""

    return [
        {
            "name": "hello",
            "envelope": _envelope(
                "hello",
                "hello-1",
                {
                    "client": "birkin-macos",
                    "client_version": "0.1.0",
                    "supported_protocol_versions": [NATIVE_PROTOCOL_VERSION],
                },
            ),
        },
        {
            "name": "ready",
            "envelope": _envelope(
                "ready",
                "ready-1",
                {
                    "server": "birkin",
                    "instance_id": "birkin-local",
                    "capability": {
                        "token": "cap-token-1",
                        "expires_in_seconds": 900,
                    },
                    "surfaces": ["session", "conversation"],
                },
                in_reply_to="hello-1",
            ),
        },
    ]


def render_fixture() -> str:
    """Render the fixture document, checking every frame round-trips first."""

    vectors: list[dict[str, object]] = []
    for vector in build_vectors():
        envelope = vector["envelope"]
        assert isinstance(envelope, dict)
        frame = encode_frame(envelope)
        decoded = decode_frame(frame)
        if decoded.to_dict() != envelope:
            raise SystemExit(f"vector {vector['name']!r} does not round-trip")
        vectors.append(
            {
                "name": vector["name"],
                "kind": envelope["kind"],
                "envelope": envelope,
                "frame_base64": base64.b64encode(frame).decode("ascii"),
                "frame_byte_count": len(frame),
            }
        )
    document = {
        "generated_by": "scripts/native/generate_golden_vectors.py",
        "source_module": "birkin.native.protocol",
        "protocol": {
            "name": NATIVE_PROTOCOL_NAME,
            "version": NATIVE_PROTOCOL_VERSION,
            "max_frame_bytes": MAX_FRAME_BYTES,
            "max_json_depth": MAX_JSON_DEPTH,
        },
        "vectors": vectors,
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ = FIXTURE_PATH.write_text(render_fixture(), encoding="utf-8")
    print(f"wrote {FIXTURE_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
