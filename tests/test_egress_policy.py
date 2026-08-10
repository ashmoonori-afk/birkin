"""Exact destination, DNS, and authentication policy tests."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import pytest

from birkin.egress_policy import canonicalize, endpoint_from_config
from birkin.llm import LLMClient
from birkin.tools import ToolContext, build_registry


def _config() -> dict[str, Any]:
    return {
        "redact_secrets": False,
        "egress": {
            "enabled": True,
            "enforced": True,
            "max_bytes": 4096,
            "destinations": {
                "trusted": {
                    "url": "https://example.com/upload",
                    "method": "POST",
                    "automatic": True,
                    "content_types": ["application/json", "text/plain"],
                    "max_bytes": 1024,
                },
            },
        },
    }


def _registry(tmp_path: Path):
    ctx = ToolContext(
        cfg=_config(),
        client=LLMClient(
            provider="",
            model="",
            api_key="",
            base_url="",
        ),
        cwd=tmp_path,
        skills=None,
        memory=None,
    )
    registry = build_registry(ctx)
    assert "submit_payload" in registry.names()
    return registry


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/upload",
        "https://user@example.com/upload",
        "https://example.com/upload?leak=value",
        "https://example.com:444/upload",
    ],
)
def test_destination_profile_requires_exact_https(
    tmp_path: Path,
    monkeypatch,
    url: str,
) -> None:
    cfg = _config()
    cfg["egress"]["destinations"]["trusted"]["url"] = url
    registry = build_registry(ToolContext(
        cfg=cfg,
        client=LLMClient(
            provider="",
            model="",
            api_key="",
            base_url="",
        ),
        cwd=tmp_path,
        skills=None,
        memory=None,
    ))
    from birkin import egress

    calls: list[str] = []
    monkeypatch.setattr(
        egress,
        "_resolve_public",
        lambda _endpoint: calls.append("resolve"),
    )

    result = registry.execute(
        "submit_payload",
        {
            "destination": "trusted",
            "payload": "{}",
            "content_type": "application/json",
        },
    )

    assert result.is_error
    assert calls == []


def test_unicode_destination_path_is_rejected_before_socket_open(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config()
    cfg["egress"]["destinations"]["trusted"]["url"] = (
        "https://example.com/한글")
    registry = build_registry(ToolContext(
        cfg=cfg,
        client=LLMClient(
            provider="",
            model="",
            api_key="",
            base_url="",
        ),
        cwd=tmp_path,
        skills=None,
        memory=None,
    ))
    from birkin import egress

    socket_calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        egress,
        "_resolve_public",
        lambda _endpoint: "93.184.216.34",
    )
    monkeypatch.setattr(egress, "_write_receipt", lambda *_args: None)

    def create_connection(
        address: tuple[str, int],
        **_kwargs: Any,
    ) -> socket.socket:
        socket_calls.append(address)
        raise OSError("socket tripwire")

    monkeypatch.setattr(socket, "create_connection", create_connection)

    result = registry.execute(
        "submit_payload",
        {
            "destination": "trusted",
            "payload": "{}",
            "content_type": "application/json",
        },
    )

    assert result.is_error
    assert socket_calls == []


def test_invalid_auth_header_is_rejected_before_socket_open(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config()
    destination = cfg["egress"]["destinations"]["trusted"]
    destination["auth_env"] = "BIRKIN_TEST_EGRESS_TOKEN"
    destination["auth_header"] = "X:Injected"
    registry = build_registry(ToolContext(
        cfg=cfg,
        client=LLMClient(
            provider="",
            model="",
            api_key="",
            base_url="",
        ),
        cwd=tmp_path,
        skills=None,
        memory=None,
    ))
    from birkin import egress

    socket_calls: list[tuple[str, int]] = []
    monkeypatch.setenv("BIRKIN_TEST_EGRESS_TOKEN", "ordinary-test-token")
    monkeypatch.setattr(
        egress,
        "_resolve_public",
        lambda _endpoint: "93.184.216.34",
    )
    monkeypatch.setattr(egress, "_write_receipt", lambda *_args: None)

    def create_connection(
        address: tuple[str, int],
        **_kwargs: Any,
    ) -> socket.socket:
        socket_calls.append(address)
        raise OSError("socket tripwire")

    monkeypatch.setattr(socket, "create_connection", create_connection)

    result = registry.execute(
        "submit_payload",
        {
            "destination": "trusted",
            "payload": "{}",
            "content_type": "application/json",
        },
    )

    assert result.is_error
    assert socket_calls == []


@pytest.mark.parametrize(
    ("auth_scheme", "credential"),
    [
        ("한글", "ordinary-test-token"),
        ("Bearer", "line-one\nline-two"),
    ],
    ids=["non-ascii-scheme", "credential-control-character"],
)
def test_invalid_auth_header_value_is_rejected_before_socket_open(
    tmp_path: Path,
    monkeypatch,
    auth_scheme: str,
    credential: str,
) -> None:
    cfg = _config()
    destination = cfg["egress"]["destinations"]["trusted"]
    destination["auth_env"] = "BIRKIN_TEST_EGRESS_TOKEN"
    destination["auth_header"] = "Authorization"
    destination["auth_scheme"] = auth_scheme
    registry = build_registry(ToolContext(
        cfg=cfg,
        client=LLMClient(
            provider="",
            model="",
            api_key="",
            base_url="",
        ),
        cwd=tmp_path,
        skills=None,
        memory=None,
    ))
    from birkin import egress

    socket_calls: list[tuple[str, int]] = []
    receipts: list[dict[str, Any]] = []
    monkeypatch.setenv("BIRKIN_TEST_EGRESS_TOKEN", credential)
    monkeypatch.setattr(
        egress,
        "_resolve_public",
        lambda _endpoint: "93.184.216.34",
    )
    monkeypatch.setattr(
        egress,
        "_write_receipt",
        lambda _cfg, record: receipts.append(dict(record)),
    )

    def create_connection(
        address: tuple[str, int],
        **_kwargs: Any,
    ) -> socket.socket:
        socket_calls.append(address)
        raise OSError("socket tripwire")

    monkeypatch.setattr(socket, "create_connection", create_connection)

    result = registry.execute(
        "submit_payload",
        {
            "destination": "trusted",
            "payload": "{}",
            "content_type": "application/json",
        },
    )

    assert result.is_error
    assert socket_calls == []
    assert receipts[-1]["state"] == "failed-before-send"


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["169.254.169.254"],
        ["93.184.216.34", "10.0.0.1"],
    ],
)
def test_private_or_mixed_dns_answers_block_before_send(
    tmp_path: Path,
    monkeypatch,
    addresses: list[str],
) -> None:
    registry = _registry(tmp_path)
    from birkin import egress

    sent: list[str] = []
    receipts: list[dict[str, Any]] = []
    monkeypatch.setattr(
        egress,
        "_write_receipt",
        lambda _cfg, record: receipts.append(dict(record)),
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, 443),
            )
            for address in addresses
        ],
    )
    monkeypatch.setattr(
        egress,
        "_send_https",
        lambda *_args: sent.append("send"),
    )

    result = registry.execute(
        "submit_payload",
        {
            "destination": "trusted",
            "payload": "{}",
            "content_type": "application/json",
        },
    )

    assert result.is_error
    assert sent == []
    assert receipts[-1]["state"] == "failed-before-send"


def test_missing_destination_auth_fails_before_send(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config()
    cfg["egress"]["destinations"]["trusted"]["auth_env"] = (
        "BIRKIN_MISSING_EGRESS_TOKEN")
    registry = build_registry(ToolContext(
        cfg=cfg,
        client=LLMClient(
            provider="",
            model="",
            api_key="",
            base_url="",
        ),
        cwd=tmp_path,
        skills=None,
        memory=None,
    ))
    from birkin import egress

    receipts: list[dict[str, Any]] = []
    sent: list[str] = []
    monkeypatch.delenv("BIRKIN_MISSING_EGRESS_TOKEN", raising=False)
    monkeypatch.setattr(
        egress,
        "_resolve_public",
        lambda _endpoint: "93.184.216.34",
    )
    monkeypatch.setattr(
        egress,
        "_write_receipt",
        lambda _cfg, record: receipts.append(dict(record)),
    )
    monkeypatch.setattr(
        egress,
        "_send_https",
        lambda *_args: sent.append("send"),
    )

    result = registry.execute(
        "submit_payload",
        {
            "destination": "trusted",
            "payload": "{}",
            "content_type": "application/json",
        },
    )

    assert result.is_error
    assert sent == []
    assert receipts[-1]["state"] == "failed-before-send"


def test_payload_within_configured_limit_is_scannable() -> None:
    cfg = _config()
    cfg["egress"]["max_bytes"] = 100_000
    cfg["egress"]["destinations"]["trusted"]["max_bytes"] = 100_000
    endpoint = endpoint_from_config(cfg, "trusted")

    body = canonicalize(
        "a" * 70_000,
        "text/plain",
        endpoint,
        cfg,
    )

    assert len(body) == 70_000
