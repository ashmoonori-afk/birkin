"""Metadata receipt coverage for enforced web and market network tools."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from birkin.tools import ToolContext
from birkin.tools import market as market_tools
from birkin.tools import web as web_tools


class _Response:
    status = 200
    headers = {"Content-Type": "text/plain; charset=utf-8"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int) -> bytes:
        return b"web-body-secret"


class _Opener:
    def open(self, *_args, **_kwargs):
        return _Response()


def _context(tmp_path: Path) -> ToolContext:
    return ToolContext(
        cfg={"egress": {"enabled": True, "enforced": True}},
        client=None,
        cwd=tmp_path,
        skills=None,
        memory=None,
    )


def _receipts(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "egress-receipts.jsonl"
    assert path.is_file()
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def test_enforced_web_fetch_records_metadata_only_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setattr(
        web_tools.urllib.request,
        "build_opener",
        lambda *_handlers: _Opener(),
    )

    result = web_tools._web_fetch(
        {"url": "https://example.com/resource?q=web-query-secret"},
        _context(tmp_path),
    )

    assert not result.is_error
    receipts = _receipts(tmp_path)
    assert receipts[-1]["operation"] == "web_fetch"
    assert receipts[-1]["outcome"] == "sent"
    serialized = json.dumps(receipts[-1], sort_keys=True)
    assert "web-query-secret" not in serialized
    assert "web-body-secret" not in serialized


def test_enforced_web_search_records_metadata_only_provider_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setattr(
        web_tools,
        "_get_json",
        lambda *_args, **_kwargs: {
            "results": [
                {
                    "url": "https://result.example/private-result-marker",
                    "title": "Private result title",
                    "description": "Private result snippet",
                },
            ],
        },
    )

    result = web_tools._web_search(
        {"query": "query-leak-marker", "count": 1},
        _context(tmp_path),
    )

    assert not result.is_error
    receipts = _receipts(tmp_path)
    assert [record["outcome"] for record in receipts] == [
        "prepared",
        "sent",
    ]
    assert {record["operation"] for record in receipts} == {"web_search"}
    assert {record["provider"] for record in receipts} == {"marginalia"}
    assert len({record["receipt_id"] for record in receipts}) == 1
    serialized = json.dumps(receipts, sort_keys=True)
    assert "query-leak-marker" not in serialized
    assert "private-result-marker" not in serialized
    assert "Private result" not in serialized


def test_enforced_web_search_records_failed_provider_attempts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))

    def fail_provider(*_args, **_kwargs):
        raise OSError("offline provider failure")

    monkeypatch.setattr(web_tools, "_get_json", fail_provider)

    result = web_tools._web_search(
        {"query": "failed-query-marker", "count": 1},
        _context(tmp_path),
    )

    assert result.is_error
    receipts = _receipts(tmp_path)
    assert [record["outcome"] for record in receipts] == [
        "prepared",
        "failed",
        "prepared",
        "failed",
    ]
    assert [record["provider"] for record in receipts] == [
        "marginalia",
        "marginalia",
        "mwmbl",
        "mwmbl",
    ]
    assert "failed-query-marker" not in json.dumps(receipts, sort_keys=True)


def test_enforced_web_search_prepared_receipt_failure_blocks_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provider_calls: list[str] = []

    def fail_receipt(*_args, **_kwargs):
        raise OSError("receipt storage unavailable")

    def provider_tripwire(*_args, **_kwargs):
        provider_calls.append("provider")
        return {"results": []}

    monkeypatch.setattr(web_tools, "record_tool_receipt", fail_receipt)
    monkeypatch.setattr(web_tools, "_get_json", provider_tripwire)

    result = web_tools._web_search(
        {"query": "must-not-send", "count": 1},
        _context(tmp_path),
    )

    assert result.is_error
    assert provider_calls == []


@dataclass
class _Quote:
    symbol: str


def test_enforced_market_quote_records_metadata_only_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))
    monkeypatch.setattr(
        market_tools,
        "_fetch_chart",
        lambda _symbol: ({}, "https://query1.finance.yahoo.com/chart"),
    )
    monkeypatch.setattr(
        market_tools,
        "parse_chart",
        lambda *_args, **_kwargs: _Quote(symbol="AAPL"),
    )

    result = market_tools._market_quote(
        {"symbols": ["AAPL"]},
        _context(tmp_path),
    )

    assert not result.is_error
    receipts = _receipts(tmp_path)
    assert receipts[-1]["operation"] == "market_quote"
    assert receipts[-1]["outcome"] == "sent"
    serialized = json.dumps(receipts[-1], sort_keys=True)
    assert "query1.finance.yahoo.com/chart" not in serialized
