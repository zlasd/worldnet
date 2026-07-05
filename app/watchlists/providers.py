from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Callable

import httpx


class InstrumentLookupError(ValueError):
    pass


@dataclass(frozen=True)
class SymbolIdentity:
    market: str
    exchange: str
    ticker: str


@dataclass(frozen=True)
class InstrumentDraft:
    market: str
    exchange: str
    ticker: str
    company_name: str
    local_name: str | None = None
    aliases: list[str] | None = None
    sector: str | None = None
    industry: str | None = None
    currency: str = "USD"


def infer_a_share_exchange(ticker: str) -> str:
    if ticker.startswith(("60", "68", "90")):
        return "SSE"
    if ticker.startswith(("00", "30", "20")):
        return "SZSE"
    if ticker.startswith(("43", "83", "87", "92")):
        return "BSE"
    raise InstrumentLookupError(f"Cannot infer A-share exchange for ticker '{ticker}'.")


def parse_symbol(
    symbol: str,
    *,
    market: str | None = None,
    exchange: str | None = None,
) -> SymbolIdentity:
    raw = symbol.strip()
    if not raw:
        raise InstrumentLookupError("Symbol cannot be empty.")

    market_override = market.upper() if market else None
    exchange_override = exchange.upper() if exchange else None
    upper = raw.upper().replace("_", "-")

    if ":" in upper:
        prefix, value = upper.split(":", 1)
        value = value.strip()
        if prefix in {"SH", "SSE"}:
            return SymbolIdentity("CN", exchange_override or "SSE", value.zfill(6))
        if prefix in {"SZ", "SZSE"}:
            return SymbolIdentity("CN", exchange_override or "SZSE", value.zfill(6))
        if prefix in {"BJ", "BSE"}:
            return SymbolIdentity("CN", exchange_override or "BSE", value.zfill(6))
        if prefix == "HK":
            return SymbolIdentity("HK", exchange_override or "HKEX", str(int(value)).zfill(4))
        if prefix == "US":
            return SymbolIdentity("US", exchange_override or "NASDAQ", value)
        return SymbolIdentity(market_override or "US", exchange_override or prefix, value)

    if upper.endswith(".HK"):
        value = upper[:-3]
        if not value.isdigit():
            raise InstrumentLookupError(f"Invalid HK symbol '{symbol}'.")
        return SymbolIdentity("HK", exchange_override or "HKEX", str(int(value)).zfill(4))

    if re.fullmatch(r"(SH|SZ|BJ)\d{6}", upper):
        prefix = upper[:2]
        ticker = upper[2:]
        exchange_map = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}
        return SymbolIdentity("CN", exchange_override or exchange_map[prefix], ticker)

    if re.fullmatch(r"\d{6}", upper):
        return SymbolIdentity("CN", exchange_override or infer_a_share_exchange(upper), upper)

    if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", upper):
        return SymbolIdentity(market_override or "US", exchange_override or "NASDAQ", upper)

    raise InstrumentLookupError(f"Cannot parse symbol '{symbol}'.")


def _decode_response(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "").lower()
    if "charset=" in content_type:
        return response.text
    try:
        return response.content.decode("gbk")
    except UnicodeDecodeError:
        return response.text


def _sina_code(identity: SymbolIdentity) -> str:
    if identity.market == "CN":
        prefix = {"SSE": "sh", "SZSE": "sz", "BSE": "bj"}[identity.exchange]
        return f"{prefix}{identity.ticker}"
    if identity.market == "HK":
        return f"hk0{identity.ticker}" if len(identity.ticker) == 4 else f"hk{identity.ticker}"
    raise InstrumentLookupError(f"Sina does not support market '{identity.market}'.")


def fetch_sina(identity: SymbolIdentity, timeout_seconds: float = 10.0) -> InstrumentDraft:
    code = _sina_code(identity)
    response = httpx.get(
        f"https://hq.sinajs.cn/list={code}",
        headers={"Referer": "https://finance.sina.com.cn"},
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        response.raise_for_status()
    text = _decode_response(response)
    match = re.search(r'="([^"]*)"', text)
    fields = match.group(1).split(",") if match else []
    name = fields[0].strip() if fields else ""
    if not name:
        raise InstrumentLookupError("Sina returned empty instrument name.")
    currency = "CNY" if identity.market == "CN" else "HKD"
    return InstrumentDraft(
        market=identity.market,
        exchange=identity.exchange,
        ticker=identity.ticker,
        company_name=name,
        local_name=name,
        aliases=[name],
        currency=currency,
    )


def _eastmoney_secid(identity: SymbolIdentity) -> str:
    if identity.market == "CN":
        prefix = {"SSE": "1", "SZSE": "0", "BSE": "0"}[identity.exchange]
        return f"{prefix}.{identity.ticker}"
    if identity.market == "HK":
        return f"116.{identity.ticker}"
    if identity.market == "US":
        return f"105.{identity.ticker}"
    raise InstrumentLookupError(f"Eastmoney does not support market '{identity.market}'.")


def fetch_eastmoney(identity: SymbolIdentity, timeout_seconds: float = 10.0) -> InstrumentDraft:
    response = httpx.get(
        "https://push2.eastmoney.com/api/qt/stock/get",
        params={"secid": _eastmoney_secid(identity), "fields": "f58,f107,f127,f116,f117"},
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise InstrumentLookupError("Eastmoney returned no data.")
    name = str(data.get("f58") or "").strip()
    if not name:
        raise InstrumentLookupError("Eastmoney returned empty instrument name.")
    currency = {"CN": "CNY", "HK": "HKD", "US": "USD"}[identity.market]
    return InstrumentDraft(
        market=identity.market,
        exchange=identity.exchange,
        ticker=identity.ticker,
        company_name=name,
        local_name=name if identity.market != "US" else None,
        aliases=[name],
        currency=currency,
    )


def _yahoo_symbol(identity: SymbolIdentity) -> str:
    if identity.market == "HK":
        return f"{int(identity.ticker):04d}.HK"
    if identity.market == "US":
        return identity.ticker
    if identity.market == "CN":
        suffix = {"SSE": "SS", "SZSE": "SZ", "BSE": "BJ"}[identity.exchange]
        return f"{identity.ticker}.{suffix}"
    raise InstrumentLookupError(f"Yahoo does not support market '{identity.market}'.")


def fetch_yahoo(identity: SymbolIdentity, timeout_seconds: float = 10.0) -> InstrumentDraft:
    response = httpx.get(
        "https://query1.finance.yahoo.com/v7/finance/quote",
        params={"symbols": _yahoo_symbol(identity)},
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        response.raise_for_status()
    payload = response.json()
    result = payload.get("quoteResponse", {}).get("result", [])
    if not result:
        raise InstrumentLookupError("Yahoo returned no data.")
    data = result[0]
    name = str(data.get("longName") or data.get("shortName") or "").strip()
    if not name:
        raise InstrumentLookupError("Yahoo returned empty instrument name.")
    currency = str(data.get("currency") or {"CN": "CNY", "HK": "HKD", "US": "USD"}[identity.market])
    exchange = str(data.get("fullExchangeName") or identity.exchange).upper().replace(" ", "_")
    return InstrumentDraft(
        market=identity.market,
        exchange=identity.exchange if identity.market in {"CN", "HK"} else exchange,
        ticker=identity.ticker,
        company_name=name,
        local_name=None if identity.market == "US" else name,
        aliases=[name],
        currency=currency,
    )


def fetch_stooq(identity: SymbolIdentity, timeout_seconds: float = 10.0) -> InstrumentDraft:
    if identity.market != "US":
        raise InstrumentLookupError("Stooq provider is only used for US symbols.")
    response = httpx.get(
        "https://stooq.com/q/l/",
        params={"s": f"{identity.ticker.lower()}.us", "f": "sd2t2ohlcvn", "h": "", "e": "csv"},
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        response.raise_for_status()
    lines = [line.strip() for line in response.text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise InstrumentLookupError("Stooq returned no data.")
    headers = lines[0].split(",")
    values = lines[1].split(",")
    data = dict(zip(headers, values, strict=False))
    name = str(data.get("Name") or identity.ticker).strip()
    if not name or name.upper() == "N/D":
        raise InstrumentLookupError("Stooq returned empty instrument name.")
    return InstrumentDraft(
        market=identity.market,
        exchange=identity.exchange,
        ticker=identity.ticker,
        company_name=name,
        aliases=[name],
        currency="USD",
    )


PROVIDERS: dict[str, Callable[[SymbolIdentity], InstrumentDraft]] = {
    "sina": fetch_sina,
    "eastmoney": fetch_eastmoney,
    "yahoo": fetch_yahoo,
    "stooq": fetch_stooq,
}


def _provider_order(identity: SymbolIdentity, provider: str) -> list[str]:
    if provider != "auto":
        return [provider]
    if identity.market == "CN":
        return ["sina", "eastmoney", "yahoo"]
    if identity.market == "HK":
        return ["sina", "yahoo", "eastmoney"]
    if identity.market == "US":
        return ["yahoo", "stooq", "eastmoney"]
    return ["yahoo"]


def resolve_instrument(
    symbol: str,
    *,
    provider: str = "auto",
    market: str | None = None,
    exchange: str | None = None,
    name: str | None = None,
    local_name: str | None = None,
) -> InstrumentDraft:
    identity = parse_symbol(symbol, market=market, exchange=exchange)
    errors: list[str] = []
    for provider_name in _provider_order(identity, provider):
        fetcher = PROVIDERS.get(provider_name)
        if fetcher is None:
            errors.append(f"unknown_provider:{provider_name}")
            continue
        try:
            draft = fetcher(identity)
            if name:
                draft = replace(draft, company_name=name)
            if local_name:
                draft = replace(draft, local_name=local_name)
            return draft
        except Exception as exc:
            errors.append(f"{provider_name}:{exc}")

    if not name:
        raise InstrumentLookupError("; ".join(errors) or "instrument_lookup_failed")
    currency = {"CN": "CNY", "HK": "HKD", "US": "USD"}.get(identity.market, "USD")
    return InstrumentDraft(
        market=identity.market,
        exchange=identity.exchange,
        ticker=identity.ticker,
        company_name=name,
        local_name=local_name,
        aliases=[value for value in [name, local_name] if value],
        currency=currency,
    )


def instrument_draft_to_item(draft: InstrumentDraft) -> dict:
    return {
        "market": draft.market,
        "exchange": draft.exchange,
        "ticker": draft.ticker,
        "company_name": draft.company_name,
        "local_name": draft.local_name,
        "aliases": draft.aliases,
        "sector": draft.sector,
        "industry": draft.industry,
        "currency": draft.currency,
    }


def instrument_draft_to_json(draft: InstrumentDraft) -> str:
    return json.dumps(instrument_draft_to_item(draft), ensure_ascii=False, indent=2)
