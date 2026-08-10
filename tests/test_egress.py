"""Inspected egress integration and capability-boundary tests."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from birkin import promptgate
from birkin.llm import LLMClient
from birkin.tools import ToolContext, build_registry
from birkin.tools import market as market_tools
from birkin.tools import web as web_tools


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


def test_blocked_receipt_counts_utf8_payload_bytes(monkeypatch):
    from birkin import egress
    from birkin.egress_policy import EgressError

    secret = "비밀값여덟글자이상"
    payload = f"전송:{secret}"
    receipts: list[dict[str, Any]] = []
    monkeypatch.setenv("BIRKIN_UTF8_SECRET", secret)
    monkeypatch.setattr(
        egress,
        "_write_receipt",
        lambda _cfg, record: receipts.append(dict(record)),
    )
    monkeypatch.setattr(
        egress,
        "_resolve_public",
        lambda _endpoint: pytest.fail("blocked payload reached DNS"),
    )

    with pytest.raises(EgressError):
        egress.submit_payload(
            _config(),
            "trusted",
            payload,
            "text/plain",
        )

    assert receipts[-1]["state"] == "blocked"
    assert receipts[-1]["bytes"] == len(payload.encode("utf-8"))
    assert receipts[-1]["bytes"] != len(payload)


def test_enforced_egress_omits_native_raw_network_tools(
    tmp_path: Path,
) -> None:
    names = set(_registry(tmp_path).names())
    assert "submit_payload" in names
    assert "run_shell" not in names
    assert "spawn_subagent" not in names


def test_explicit_enforcement_opt_out_restores_native_tools(
    tmp_path: Path,
) -> None:
    cfg = _config()
    cfg["egress"]["enforced"] = False
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
    names = set(registry.names())
    assert "run_shell" in names
    assert "spawn_subagent" in names


def test_disabled_egress_is_not_advertised_by_native_registry(
    tmp_path: Path,
) -> None:
    cfg = _config()
    cfg["egress"]["enabled"] = False
    client = LLMClient(
        provider="",
        model="",
        api_key="",
        base_url="",
    )
    registry = build_registry(ToolContext(
        cfg=cfg,
        client=client,
        cwd=tmp_path,
        skills=None,
        memory=None,
    ))

    assert "submit_payload" not in registry.names()


def test_enforced_agent_prompt_omits_unavailable_subagent_tool() -> None:
    cfg = _config()
    system = promptgate.compose_main(cfg, persona_text="")

    assert "spawn_subagent" not in system


def test_enforced_egress_scans_web_url_and_query_before_network(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config()
    ctx = ToolContext(
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
    )
    secret = "runtime-web-secret-123456"
    calls: list[str] = []
    monkeypatch.setenv("BIRKIN_TEST_WEB_TOKEN", secret)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: calls.append("dns"),
    )
    monkeypatch.setattr(
        web_tools,
        "_marginalia",
        lambda *_args: calls.append("search"),
    )
    fetch = next(
        tool for tool in web_tools.tools() if tool.name == "web_fetch").fn
    search = next(
        tool for tool in web_tools.tools() if tool.name == "web_search").fn

    fetched = fetch(
        {"url": f"https://example.com/?q={secret}"},
        ctx,
    )
    searched = search({"query": secret}, ctx)

    assert fetched.is_error
    assert searched.is_error
    assert calls == []


def test_enforced_egress_scans_market_symbols_before_network(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _config()
    ctx = ToolContext(
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
    )
    secret = "ABCDEF1234567890"
    calls: list[str] = []
    monkeypatch.setenv("BIRKIN_MARKET_SECRET_TOKEN", secret)
    monkeypatch.setattr(
        market_tools,
        "_fetch_chart",
        lambda symbol: calls.append(symbol) or ({}, ""),
    )
    quote = next(
        tool for tool in market_tools.tools() if tool.name == "market_quote"
    ).fn

    result = quote({"symbols": [secret]}, ctx)

    assert result.is_error
    assert calls == []


def test_trusted_clean_payload_auto_sends_exact_canonical_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = _registry(tmp_path)
    calls, receipts = _install_safe_fakes(monkeypatch)

    result = registry.execute(
        "submit_payload",
        {
            "destination": "trusted",
            "payload": '{"answer": 42}',
            "content_type": "application/json",
        },
    )

    assert not result.is_error
    assert isinstance(result.content, str)
    visible = json.loads(result.content)
    assert visible["state"] == "succeeded"
    assert visible["destination"] == "trusted"
    assert "payload" not in visible
    sent = next(call for call in calls if call["kind"] == "send")
    assert sent["body"] == b'{"answer":42}'
    assert len(receipts) == 2
    serialized = json.dumps(receipts)
    assert "answer" not in serialized
    assert "remote-1" not in serialized


def test_submit_payload_is_available_only_in_full_mcp_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    from birkin import config
    from birkin.mcp_server import _build_tools

    config.save_config({**config.DEFAULT_CONFIG, "egress": _config()["egress"]})
    monkeypatch.setenv("BIRKIN_MCP_SCOPE", "full")
    loaded = config.load_config()
    full_tools = _build_tools()
    assert "submit_payload" in full_tools, {
        "egress": loaded.get("egress"),
        "disabled_tools": loaded.get("disabled_tools"),
        "tools": sorted(full_tools),
    }

    monkeypatch.setenv("BIRKIN_MCP_SCOPE", "memory")
    assert "submit_payload" not in _build_tools()
