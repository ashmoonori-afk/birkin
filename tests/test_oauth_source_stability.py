from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


def _credential(access: str, refresh: str, expired: bool) -> dict[str, object]:
    return {
        "claudeAiOauth": {
            "accessToken": access,
            "refreshToken": refresh,
            "expiresAt": int(time.time() * 1000)
            + (-60_000 if expired else 3_600_000),
        }
    }


def _extracted(access: str, refresh: str, source: str) -> dict[str, object]:
    return {
        "accessToken": access,
        "refreshToken": refresh,
        "expiresAt": int(time.time() * 1000) - 60_000,
        "scopes": None,
        "source": source,
    }


def _fresh(access: str, refresh: str) -> dict[str, object]:
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at_ms": int(time.time() * 1000) + 3_600_000,
    }


def test_file_refresh_is_not_shadowed_by_external_keychain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from birkin import oauth

    path = tmp_path / ".credentials.json"
    _ = path.write_text(
        json.dumps(_credential("STALE-FILE", "R1", True)), encoding="utf-8"
    )
    stale_external = _extracted("STALE-KEYCHAIN", "EXTERNAL", "macos_keychain")
    calls = 0

    def external_after_source_selected() -> dict[str, object] | None:
        nonlocal calls
        calls += 1
        return None if calls == 1 else stale_external

    def refresh_file(_token: str) -> dict[str, object]:
        return _fresh("FRESH-FILE", "R2")

    monkeypatch.setattr(oauth, "_credentials_path", lambda: path)
    monkeypatch.setattr(oauth, "_read_keychain", external_after_source_selected)
    monkeypatch.setattr(oauth, "refresh", refresh_file)
    monkeypatch.setattr(oauth, "_preferred_source", None)
    monkeypatch.setattr(oauth, "_refreshed_credentials", None)

    assert oauth.resolve_token() == "FRESH-FILE"
    reread = oauth.read_credentials()
    assert reread is not None
    assert reread["source"] == "credentials_file"
    assert reread["accessToken"] == "FRESH-FILE"


def test_keychain_refresh_never_writes_the_external_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from birkin import oauth

    path = tmp_path / ".credentials.json"
    keychain = _extracted("STALE-KEYCHAIN", "EXTERNAL", "macos_keychain")

    def read_keychain() -> dict[str, object]:
        return keychain

    def refresh_keychain(_token: str) -> dict[str, object]:
        return _fresh("FRESH-MEMORY", "ROTATED")

    writes: list[tuple[str, str, int, list[object] | None]] = []

    def record_write(
        access: str,
        refresh_token: str,
        expires_at_ms: int,
        scopes: list[object] | None = None,
    ) -> None:
        writes.append((access, refresh_token, expires_at_ms, scopes))

    monkeypatch.setattr(oauth, "_credentials_path", lambda: path)
    monkeypatch.setattr(oauth, "_read_keychain", read_keychain)
    monkeypatch.setattr(oauth, "refresh", refresh_keychain)
    monkeypatch.setattr(oauth, "_preferred_source", None)
    monkeypatch.setattr(oauth, "_refreshed_credentials", None)
    monkeypatch.setattr(oauth, "_write_credentials", record_write)

    assert oauth.resolve_token() == "FRESH-MEMORY"
    assert writes == []
    assert not path.exists()
