"""Deterministic market-price parsing and agent tool contracts."""

from __future__ import annotations

import importlib
import importlib.util
import json
from datetime import datetime, timezone
from typing import TypeAlias

import pytest

from birkin import mcp_server
from birkin.gateway import workflow

JsonValue: TypeAlias = (
    str | int | float | bool | None
    | list["JsonValue"]
    | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]


def _market_module():
    spec = importlib.util.find_spec("birkin.tools.market")
    assert spec is not None, "birkin.tools.market must provide verified quotes"
    return importlib.import_module("birkin.tools.market")


def _chart_payload(
    *,
    price: float = 209_500.0,
    market_time: int = 1_785_381_305,
) -> JsonObject:
    return {
        "chart": {
            "result": [{
                "meta": {
                    "currency": "KRW",
                    "symbol": "005930.KS",
                    "exchangeName": "KSC",
                    "fullExchangeName": "KSE",
                    "regularMarketTime": market_time,
                    "regularMarketPrice": price,
                    "chartPreviousClose": 270_000.0,
                    "gmtoffset": 32_400,
                    "exchangeTimezoneName": "Asia/Seoul",
                    "longName": "Samsung Electronics Co., Ltd.",
                    "currentTradingPeriod": {
                        "regular": {
                            "start": 1_785_369_600,
                            "end": 1_785_391_200,
                        }
                    },
                },
                "timestamp": [market_time],
                "indicators": {
                    "quote": [{
                        "close": [price],
                        "high": [226_000.0],
                        "low": [202_000.0],
                    }]
                },
            }],
            "error": None,
        }
    }


def test_parse_chart_preserves_price_currency_timestamp_and_source() -> None:
    # Given
    market = _market_module()
    source = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        "005930.KS?range=5d&interval=1d"
    )

    # When
    quote = market.parse_chart(
        _chart_payload(),
        source_url=source,
        now=datetime(2026, 7, 30, 12, 40, tzinfo=timezone.utc),
    )

    # Then
    assert quote.symbol == "005930.KS"
    assert quote.price == 209_500.0
    assert quote.currency == "KRW"
    assert quote.exchange == "KSE"
    assert quote.as_of.startswith("2026-07-30T")
    assert quote.as_of.endswith("+09:00")
    assert quote.source_url == source


def test_parse_chart_rejects_stale_price() -> None:
    # Given
    market = _market_module()
    stale = _chart_payload(market_time=1_700_000_000)

    # When / Then
    with pytest.raises(market.MarketQuoteError, match="stale"):
        market.parse_chart(
            stale,
            source_url="https://query1.finance.yahoo.com/example",
            now=datetime(2026, 7, 30, 12, 40, tzinfo=timezone.utc),
        )


def test_quote_tool_is_available_to_native_and_mcp_agents(
    tmp_path,
    monkeypatch,
) -> None:
    # Given
    market = _market_module()
    monkeypatch.setenv("BIRKIN_HOME", str(tmp_path))

    # When
    native_names = {tool.name for tool in market.tools()}
    mcp_names = set(mcp_server._build_tools())

    # Then
    assert "market_quote" in native_names
    assert "market_quote" in mcp_names


def test_market_quote_tool_returns_machine_readable_verified_fields(
    monkeypatch,
) -> None:
    # Given
    market = _market_module()
    source = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        "005930.KS?range=5d&interval=1d"
    )
    monkeypatch.setattr(
        market,
        "_fetch_chart",
        lambda _symbol: (_chart_payload(), source),
    )

    # When
    result = market._market_quote({"symbols": ["삼성전자"]}, None)
    payload = json.loads(result.content)

    # Then
    assert result.is_error is False
    assert payload["quotes"] == [{
        "symbol": "005930.KS",
        "name": "Samsung Electronics Co., Ltd.",
        "price": 209_500.0,
        "currency": "KRW",
        "as_of": payload["quotes"][0]["as_of"],
        "price_status": "intraday",
        "exchange": "KSE",
        "previous_close": 270_000.0,
        "day_high": 226_000.0,
        "day_low": 202_000.0,
        "source_url": source,
    }]
    assert payload["quotes"][0]["as_of"].endswith("+09:00")


def test_trusted_telegram_policy_requires_verified_market_data() -> None:
    # Given
    policy = workflow.WORKFLOW_POLICY

    # When
    open_count = policy.count(workflow.MARKET_DATA_OPEN)
    close_count = policy.count(workflow.MARKET_DATA_CLOSE)

    # Then
    assert open_count == 1
    assert close_count == 1
    assert policy.index(workflow.MARKET_DATA_OPEN) < policy.index(
        workflow.MARKET_DATA_CLOSE
    )
