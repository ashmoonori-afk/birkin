"""Verified current market quotes from Yahoo's structured chart endpoint."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..egress import record_tool_receipt
from ..egress_scan import EgressScanError, inspect_payload
from ..httpguard import PinnedHTTPSHandler
from ._types import Tool, ToolContext, ToolResult

_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
_MAX_AGE = timedelta(days=7)
_MAX_SYMBOLS = 10
_SYMBOL_RE = re.compile(r"^[A-Z0-9.^=-]{1,24}$")
_ALIASES = {
    "microsoft": "MSFT",
    "msft": "MSFT",
    "nvidia": "NVDA",
    "nvda": "NVDA",
    "삼성전자": "005930.KS",
    "samsung electronics": "005930.KS",
    "005930": "005930.KS",
    "005930.ks": "005930.KS",
    "sk하이닉스": "000660.KS",
    "sk hynix": "000660.KS",
    "000660": "000660.KS",
    "000660.ks": "000660.KS",
}


class MarketQuoteError(ValueError):
    """Structured quote data is absent, invalid, future-dated, or stale."""


@dataclass(frozen=True, slots=True)
class MarketQuote:
    symbol: str
    name: str
    price: float
    currency: str
    as_of: str
    price_status: str
    exchange: str
    previous_close: float | None
    day_high: float | None
    day_low: float | None
    source_url: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _latest(values: Any) -> float | None:
    if not isinstance(values, list):
        return None
    for value in reversed(values):
        number = _number(value)
        if number is not None:
            return number
    return None


def parse_chart(
    payload: dict[str, Any],
    *,
    source_url: str,
    now: datetime | None = None,
) -> MarketQuote:
    chart = payload.get("chart")
    if not isinstance(chart, dict) or chart.get("error"):
        raise MarketQuoteError("quote provider returned an error")
    results = chart.get("result")
    if not isinstance(results, list) or not results:
        raise MarketQuoteError("quote result is missing")
    result = results[0]
    if not isinstance(result, dict):
        raise MarketQuoteError("quote result is invalid")
    meta = result.get("meta")
    if not isinstance(meta, dict):
        raise MarketQuoteError("quote metadata is missing")

    price = _number(meta.get("regularMarketPrice"))
    market_time = _number(meta.get("regularMarketTime"))
    if price is None or price <= 0 or market_time is None:
        raise MarketQuoteError("current price or timestamp is missing")
    observed_utc = datetime.fromtimestamp(market_time, tz=timezone.utc)
    current = (now or _utc_now()).astimezone(timezone.utc)
    age = current - observed_utc
    if age > _MAX_AGE:
        raise MarketQuoteError(f"quote is stale by {age}")
    if age < -timedelta(minutes=10):
        raise MarketQuoteError("quote timestamp is in the future")

    offset = _number(meta.get("gmtoffset"))
    if offset is not None:
        exchange_timezone = timezone(timedelta(seconds=offset))
    else:
        timezone_name = str(meta.get("exchangeTimezoneName") or "UTC")
        try:
            exchange_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            exchange_timezone = timezone.utc
    observed_local = observed_utc.astimezone(exchange_timezone)
    periods = meta.get("currentTradingPeriod")
    regular = periods.get("regular") if isinstance(periods, dict) else None
    regular_start = _number(regular.get("start")) if isinstance(
        regular, dict
    ) else None
    regular_end = _number(regular.get("end")) if isinstance(
        regular, dict
    ) else None
    current_timestamp = current.timestamp()
    price_status = (
        "intraday"
        if regular_start is not None
        and regular_end is not None
        and regular_start <= current_timestamp <= regular_end
        else "latest_close"
    )
    quote_rows = (
        result.get("indicators", {}).get("quote", [])
        if isinstance(result.get("indicators"), dict)
        else []
    )
    latest_row = quote_rows[0] if quote_rows and isinstance(
        quote_rows[0], dict
    ) else {}
    return MarketQuote(
        symbol=str(meta.get("symbol") or ""),
        name=str(meta.get("longName") or meta.get("shortName") or ""),
        price=price,
        currency=str(meta.get("currency") or ""),
        as_of=observed_local.isoformat(timespec="seconds"),
        price_status=price_status,
        exchange=str(meta.get("fullExchangeName")
                     or meta.get("exchangeName") or ""),
        previous_close=_number(meta.get("chartPreviousClose")),
        day_high=(_number(meta.get("regularMarketDayHigh"))
                  or _latest(latest_row.get("high"))),
        day_low=(_number(meta.get("regularMarketDayLow"))
                 or _latest(latest_row.get("low"))),
        source_url=source_url,
    )


def _normalize_symbol(value: str) -> str:
    cleaned = value.strip()
    symbol = _ALIASES.get(cleaned.casefold(), cleaned.upper())
    if not _SYMBOL_RE.fullmatch(symbol):
        raise MarketQuoteError(f"unsupported symbol: {value!r}")
    return symbol


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            newurl,
            code,
            "market provider redirects are disabled",
            headers,
            fp,
        )


def _market_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
        PinnedHTTPSHandler(),
    )


def _fetch_chart(symbol: str) -> tuple[dict[str, Any], str]:
    encoded = urllib.parse.quote(symbol, safe=".^=-")
    url = f"{_BASE_URL}{encoded}?range=5d&interval=1d"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Birkin/market-quote"},
    )
    with _market_opener().open(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise MarketQuoteError("quote response is not an object")
    return payload, url


def _market_quote(
    inp: dict[str, Any],
    ctx: ToolContext | None,
) -> ToolResult:
    raw_symbols = inp.get("symbols")
    if not isinstance(raw_symbols, list) or not 1 <= len(
        raw_symbols
    ) <= _MAX_SYMBOLS:
        return ToolResult(
            json.dumps({"error": "symbols must contain 1 to 10 entries"}),
            is_error=True,
        )
    quotes: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for raw in raw_symbols:
        if not isinstance(raw, str):
            errors.append({"symbol": str(raw), "error": "symbol must be text"})
            continue
        try:
            if ctx is not None:
                egress = ctx.cfg.get("egress")
                if (isinstance(egress, dict)
                        and egress.get("enabled") is True
                        and egress.get("enforced") is True):
                    inspect_payload(raw, None, ctx.cfg)
            symbol = _normalize_symbol(raw)
            receipt_id = record_tool_receipt(
                ctx.cfg if ctx is not None else {},
                operation="market_quote",
                outcome="prepared",
                provider="yahoo",
            )
            try:
                payload, source_url = _fetch_chart(symbol)
            except Exception:
                record_tool_receipt(
                    ctx.cfg if ctx is not None else {},
                    operation="market_quote",
                    outcome="failed",
                    receipt_id=receipt_id,
                    provider="yahoo",
                )
                raise
            record_tool_receipt(
                ctx.cfg if ctx is not None else {},
                operation="market_quote",
                outcome="sent",
                receipt_id=receipt_id,
                provider="yahoo",
            )
            quotes.append(asdict(parse_chart(payload, source_url=source_url)))
        except (
            EgressScanError,
            MarketQuoteError,
            TimeoutError,
            UnicodeError,
            json.JSONDecodeError,
            urllib.error.URLError,
        ) as exc:
            errors.append({"symbol": raw, "error": str(exc)})
    output = {
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "quotes": quotes,
        "errors": errors,
    }
    return ToolResult(
        json.dumps(output, ensure_ascii=False, separators=(",", ":")),
        is_error=not quotes,
    )


def tools() -> list[Tool]:
    return [
        Tool(
            name="market_quote",
            description=(
                "Get verified current or latest-close prices from Yahoo's "
                "structured chart feed. Returns exact price, currency, exchange "
                "timestamp, previous close, day range, and source URL. Use this "
                "for every claimed current stock/ETF/index price; never replace "
                "it with web-search snippets."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": _MAX_SYMBOLS,
                        "description": (
                            "Tickers or supported names, e.g. MSFT, NVDA, "
                            "005930.KS, 000660.KS, 삼성전자, SK하이닉스."
                        ),
                    }
                },
                "required": ["symbols"],
            },
            fn=_market_quote,
        )
    ]
