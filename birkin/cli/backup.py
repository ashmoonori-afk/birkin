"""Export / import Birkin workspace data as portable archives."""

from __future__ import annotations

import base64
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path

MAGIC_HEADER = b"BIRKIN_EXPORT_V1"
SALT_LENGTH = 16


# ---------------------------------------------------------------------------
# Encryption helpers (require optional ``cryptography`` package)
# ---------------------------------------------------------------------------


def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from *password* + *salt* via PBKDF2."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    raw_key = kdf.derive(password.encode("utf-8"))
    return base64.urlsafe_b64encode(raw_key)


def _encrypt_bytes(data: bytes, password: str) -> bytes:
    """Return ``MAGIC + salt + Fernet(data)``."""
    from cryptography.fernet import Fernet

    salt = os.urandom(SALT_LENGTH)
    key = _derive_fernet_key(password, salt)
    token = Fernet(key).encrypt(data)
    return MAGIC_HEADER + salt + token


def _decrypt_bytes(blob: bytes, password: str) -> bytes:
    """Reverse of :func:`_encrypt_bytes`.  Raises ``ValueError`` on bad password."""
    from cryptography.fernet import Fernet, InvalidToken

    if not blob.startswith(MAGIC_HEADER):
        raise ValueError("Archive is not encrypted or has an unrecognised format.")

    rest = blob[len(MAGIC_HEADER) :]
    salt = rest[:SALT_LENGTH]
    token = rest[SALT_LENGTH:]
    key = _derive_fernet_key(password, salt)
    try:
        return Fernet(key).decrypt(token)
    except InvalidToken:
        raise ValueError("Wrong password or corrupted archive.") from None


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

_SINGLE_FILES = ("birkin_sessions.db", "birkin_config.json")


def _collect_files(base: Path) -> list[Path]:
    """Return a sorted list of workspace files relative to *base*."""
    collected: list[Path] = []

    for name in _SINGLE_FILES:
        candidate = base / name
        if candidate.is_file():
            collected.append(candidate)

    memory_dir = base / "memory"
    if memory_dir.is_dir():
        for p in sorted(memory_dir.rglob("*")):
            if p.is_file():
                collected.append(p)

    traces_dir = base / "traces"
    if traces_dir.is_dir():
        for p in sorted(traces_dir.rglob("*.jsonl")):
            if p.is_file():
                collected.append(p)

    return collected


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def export_archive(
    output_path: str | None = None,
    password: str | None = None,
    base_dir: str = ".",
) -> Path:
    """Create a portable archive of the Birkin workspace.

    Parameters
    ----------
    output_path:
        Destination file path.  Defaults to
        ``birkin-export-YYYY-MM-DD.zip`` (or ``.birkin`` when encrypted).
    password:
        When provided **and** the ``cryptography`` package is installed the
        archive is AES-encrypted with a Fernet envelope.
    base_dir:
        Root of the workspace to export (defaults to cwd).

    Returns
    -------
    Path
        The absolute path of the written archive.
    """
    base = Path(base_dir).resolve()
    files = _collect_files(base)

    # Build an in-memory zip
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in files:
            arcname = fp.relative_to(base).as_posix()
            zf.write(fp, arcname)
    zip_bytes = buf.getvalue()

    # Decide on encryption
    encrypted = False
    if password:
        try:
            import cryptography as _cg  # noqa: F401

            zip_bytes = _encrypt_bytes(zip_bytes, password)
            encrypted = True
        except ModuleNotFoundError:
            pass  # fall back to plain zip

    # Determine output path
    if output_path is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ext = ".birkin" if encrypted else ".zip"
        output_path_resolved = base / f"birkin-export-{today}{ext}"
    else:
        output_path_resolved = Path(output_path).resolve()

    output_path_resolved.parent.mkdir(parents=True, exist_ok=True)
    output_path_resolved.write_bytes(zip_bytes)
    return output_path_resolved


def import_archive(
    archive_path: str,
    password: str | None = None,
    target_dir: str = ".",
) -> dict[str, object]:
    """Restore a Birkin archive into *target_dir*.

    Parameters
    ----------
    archive_path:
        Path to the ``.zip`` or ``.birkin`` archive.
    password:
        Required when the archive is encrypted.
    target_dir:
        Destination directory (defaults to cwd).

    Returns
    -------
    dict
        Summary with keys ``files_restored``, ``sessions_db``,
        ``wiki_pages``, and ``config``.

    Raises
    ------
    FileNotFoundError
        If *archive_path* does not exist.
    ValueError
        If the password is wrong or missing for an encrypted archive.
    zipfile.BadZipFile
        If the file is not a valid zip archive.
    """
    src = Path(archive_path)
    if not src.is_file():
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    raw = src.read_bytes()

    # Detect encryption
    if raw.startswith(MAGIC_HEADER):
        if not password:
            raise ValueError("Archive is encrypted; a password is required.")
        raw = _decrypt_bytes(raw, password)

    dest = Path(target_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    files_restored = 0
    sessions_db = False
    wiki_pages = 0
    config = False

    import io

    with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target_file = dest / info.filename
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_bytes(zf.read(info.filename))
            files_restored += 1

            if info.filename == "birkin_sessions.db":
                sessions_db = True
            elif info.filename == "birkin_config.json":
                config = True
            elif info.filename.startswith("memory/"):
                wiki_pages += 1

    return {
        "files_restored": files_restored,
        "sessions_db": sessions_db,
        "wiki_pages": wiki_pages,
        "config": config,
    }
