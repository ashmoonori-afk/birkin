"""Detached, stdlib-only signatures for Birkin plugin bundles."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from pathlib import Path


class SignatureError(ValueError):
    """A bundle signature is absent, untrusted, or invalid."""


SIGNATURE_FILE = "bundle.sig"


def bundle_digest_bytes(files: Mapping[str, bytes]) -> str:
    """Hash an immutable bundle byte mapping in stable path order."""
    digest = hashlib.sha256()
    for relative, data in sorted(files.items()):
        if Path(relative).name == SIGNATURE_FILE:
            continue
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def bundle_digest(root: Path) -> str:
    """Hash paths and bytes in stable order, excluding the detached signature."""
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.name != SIGNATURE_FILE
    )
    captured: dict[str, bytes] = {}
    for path in files:
        if path.is_symlink():
            raise SignatureError(f"bundle contains a symbolic link: {path}")
        captured[path.relative_to(root).as_posix()] = path.read_bytes()
    return bundle_digest_bytes(captured)


def sign_bundle(root: Path, key_id: str, key: bytes) -> Path:
    if not key_id or not key:
        raise SignatureError("key id and key must not be empty")
    digest = bundle_digest(root)
    signature = hmac.new(key, digest.encode("ascii"), hashlib.sha256).hexdigest()
    path = root / SIGNATURE_FILE
    path.write_text(json.dumps({
        "algorithm": "hmac-sha256",
        "key_id": key_id,
        "signature": signature,
    }, sort_keys=True), encoding="utf-8")
    return path


def verify_bundle(root: Path, trusted_keys: Mapping[str, bytes], *, allow_missing: bool) -> tuple[str, str]:
    digest = bundle_digest(root)
    path = root / SIGNATURE_FILE
    if not path.is_file():
        if allow_missing:
            return digest, "unsigned-allowed"
        raise SignatureError("detached signature is missing")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SignatureError(f"invalid detached signature: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"algorithm", "key_id", "signature"}:
        raise SignatureError("invalid detached signature record")
    if raw["algorithm"] != "hmac-sha256":
        raise SignatureError(f"unsupported signature algorithm: {raw['algorithm']!r}")
    key_id = raw["key_id"]
    if not isinstance(key_id, str) or key_id not in trusted_keys:
        raise SignatureError(f"untrusted key: {key_id!r}")
    signature = raw["signature"]
    if not isinstance(signature, str):
        raise SignatureError("invalid detached signature value")
    expected = hmac.new(trusted_keys[key_id], digest.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise SignatureError("bundle signature mismatch")
    return digest, f"verified:{key_id}"
