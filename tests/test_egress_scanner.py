"""Payload scanner and receipt failure semantics."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

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
                "review-only": {
                    "url": "https://example.com/review",
                    "method": "POST",
                    "automatic": False,
                    "content_types": ["application/json"],
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


def _install_safe_fakes(monkeypatch):
    from birkin import egress

    calls: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []

    def resolve(endpoint):
        calls.append({"kind": "resolve", "host": endpoint.host})
        return "93.184.216.34"

    def send(endpoint, address, body, headers):
        calls.append({
            "kind": "send",
            "address": address,
            "body": body,
            "headers": headers,
        })
        return 201, b'{"request_id":"remote-1"}'

    def receipt(_cfg, record):
        receipts.append(dict(record))

    monkeypatch.setattr(egress, "_resolve_public", resolve)
    monkeypatch.setattr(egress, "_send_https", send)
    monkeypatch.setattr(egress, "_write_receipt", receipt)
    return calls, receipts


def test_secret_and_encoded_secret_block_before_resolution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = _registry(tmp_path)
    calls, receipts = _install_safe_fakes(monkeypatch)
    secret = "sk-ant-" + "A" * 32
    encoded = base64.b64encode(secret.encode()).decode()

    for payload in (
        json.dumps({"note": secret}),
        json.dumps({"note": encoded}),
        json.dumps({"api_key": "ordinary-looking-value"}),
    ):
        result = registry.execute(
            "submit_payload",
            {
                "destination": "trusted",
                "payload": payload,
                "content_type": "application/json",
            },
        )
        assert result.is_error
        assert "blocked" in result.content.lower()

    assert calls == []
    assert all(receipt["state"] == "blocked" for receipt in receipts)
    assert secret not in json.dumps(receipts)


def test_embedded_encoded_secret_blocks_before_resolution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = _registry(tmp_path)
    calls, _receipts = _install_safe_fakes(monkeypatch)
    secret = "sk-ant-" + "A" * 32
    encoded_values = (
        base64.b64encode(secret.encode()).decode(),
        secret.encode().hex(),
    )

    for encoded in encoded_values:
        result = registry.execute(
            "submit_payload",
            {
                "destination": "trusted",
                "payload": f"prefix {encoded} suffix",
                "content_type": "text/plain",
            },
        )
        assert result.is_error

    assert calls == []


def test_base64_secret_with_adjacent_alphabet_characters_blocks_before_resolution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = _registry(tmp_path)
    calls, _receipts = _install_safe_fakes(monkeypatch)
    secret = "runtime-secret-123456"
    monkeypatch.setenv("BIRKIN_TEST_SECRET_TOKEN", secret)
    encoded = base64.b64encode(secret.encode()).decode()

    result = registry.execute(
        "submit_payload",
        {
            "destination": "trusted",
            "payload": f"x{encoded}y",
            "content_type": "text/plain",
        },
    )

    assert result.is_error
    assert calls == []


def test_short_runtime_secret_encoded_as_base64_blocks_before_resolution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = _registry(tmp_path)
    calls, _receipts = _install_safe_fakes(monkeypatch)
    secret = "abcdefgh"
    monkeypatch.setenv("BIRKIN_TEST_SECRET_TOKEN", secret)
    encoded = base64.b64encode(secret.encode()).decode()

    result = registry.execute(
        "submit_payload",
        {
            "destination": "trusted",
            "payload": encoded,
            "content_type": "text/plain",
        },
    )

    assert result.is_error
    assert calls == []


def test_triple_base64_secret_blocks_before_resolution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = _registry(tmp_path)
    calls, _receipts = _install_safe_fakes(monkeypatch)
    secret = "runtime-secret-123456"
    monkeypatch.setenv("BIRKIN_TEST_SECRET_TOKEN", secret)
    encoded = secret
    for _depth in range(3):
        encoded = base64.b64encode(encoded.encode()).decode()

    result = registry.execute(
        "submit_payload",
        {
            "destination": "trusted",
            "payload": encoded,
            "content_type": "text/plain",
        },
    )

    assert result.is_error
    assert calls == []


def test_runtime_secret_blocks_even_when_normal_redaction_is_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = _registry(tmp_path)
    calls, _receipts = _install_safe_fakes(monkeypatch)
    monkeypatch.setenv("BIRKIN_TEST_SECRET_TOKEN", "runtime-secret-123456")

    result = registry.execute(
        "submit_payload",
        {
            "destination": "trusted",
            "payload": "runtime-secret-123456",
            "content_type": "text/plain",
        },
    )

    assert result.is_error
    assert calls == []


def test_unknown_or_nonautomatic_destination_never_resolves(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = _registry(tmp_path)
    calls, _receipts = _install_safe_fakes(monkeypatch)

    for destination in ("missing", "review-only"):
        result = registry.execute(
            "submit_payload",
            {
                "destination": destination,
                "payload": "{}",
                "content_type": "application/json",
            },
        )
        assert result.is_error

    assert calls == []


def test_intent_receipt_failure_prevents_network(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = _registry(tmp_path)
    from birkin import egress

    calls: list[str] = []
    monkeypatch.setattr(
        egress,
        "_write_receipt",
        lambda _cfg, _record: (_ for _ in ()).throw(OSError("disk full")),
    )
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


def test_non_2xx_response_is_a_tool_error_without_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = _registry(tmp_path)
    from birkin import egress

    sends: list[bytes] = []
    receipts: list[dict[str, Any]] = []
    monkeypatch.setattr(
        egress,
        "_resolve_public",
        lambda _endpoint: "93.184.216.34",
    )
    monkeypatch.setattr(
        egress,
        "_send_https",
        lambda _endpoint, _address, body, _headers: (
            sends.append(body) or (503, b"unavailable")
        ),
    )
    monkeypatch.setattr(
        egress,
        "_write_receipt",
        lambda _cfg, record: receipts.append(dict(record)),
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
    assert len(sends) == 1
    assert receipts[-1]["state"] == "failed"
    assert receipts[-1]["http_status"] == 503
