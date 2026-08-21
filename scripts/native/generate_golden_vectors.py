"""Generate cross-language golden vectors with the real Python native codec.

The macOS Swift package must decode exactly what Birkin's Python bridge emits
and re-encode byte-identical frames, so the fixtures the Swift tests consume are
produced here by ``birkin.native.protocol.encode_frame`` itself rather than by a
hand-written transcription of the wire format.

Usage (from the repository root)::

    uv run python scripts/native/generate_golden_vectors.py
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from birkin.native.protocol import (
    MAX_FRAME_BYTES,
    MAX_JSON_DEPTH,
    NATIVE_PROTOCOL_NAME,
    NATIVE_PROTOCOL_VERSION,
    decode_frame,
    encode_frame,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.native.native_vector_catalogue import build_vectors  # noqa: E402

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


def render_fixture() -> str:
    """Render the fixture document, checking every frame round-trips first."""

    vectors: list[dict[str, object]] = []
    for name, envelope in build_vectors():
        frame = encode_frame(envelope)
        if decode_frame(frame).to_dict() != envelope:
            raise SystemExit(f"vector {name!r} does not round-trip in Python")
        if encode_frame(decode_frame(frame)) != frame:
            raise SystemExit(f"vector {name!r} does not re-encode identically")
        vectors.append(
            {
                "name": name,
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
