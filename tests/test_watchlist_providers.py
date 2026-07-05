import httpx
import pytest

from app.watchlists import providers
from app.watchlists.providers import InstrumentLookupError, parse_symbol, resolve_instrument


def test_parse_a_share_symbols():
    assert parse_symbol("600519").exchange == "SSE"
    assert parse_symbol("600519").ticker == "600519"
    assert parse_symbol("000001").exchange == "SZSE"
    assert parse_symbol("SH600519").exchange == "SSE"
    assert parse_symbol("sz:000001").exchange == "SZSE"


def test_parse_hk_and_us_symbols():
    hk = parse_symbol("00700.HK")
    assert hk.market == "HK"
    assert hk.exchange == "HKEX"
    assert hk.ticker == "0700"

    us = parse_symbol("us:AAPL")
    assert us.market == "US"
    assert us.ticker == "AAPL"


def test_parse_unknown_symbol_raises_clear_error():
    with pytest.raises(InstrumentLookupError, match="Cannot parse"):
        parse_symbol("???")


def test_resolve_instrument_from_sina_cn(monkeypatch):
    def fake_get(*args, **kwargs):
        return httpx.Response(200, content='var hq_str_sh600519="贵州茅台,1,2";'.encode("gbk"))

    monkeypatch.setattr("app.watchlists.providers.httpx.get", fake_get)

    draft = resolve_instrument("600519", provider="sina")

    assert draft.market == "CN"
    assert draft.exchange == "SSE"
    assert draft.ticker == "600519"
    assert draft.company_name == "贵州茅台"
    assert draft.currency == "CNY"


def test_resolve_instrument_falls_back_to_next_provider(monkeypatch):
    def fail(_identity):
        raise InstrumentLookupError("failed")

    def success(identity):
        return providers.InstrumentDraft(
            market=identity.market,
            exchange=identity.exchange,
            ticker=identity.ticker,
            company_name="Ping An Bank",
            currency="CNY",
        )

    monkeypatch.setattr(providers, "PROVIDERS", {"sina": fail, "eastmoney": success})

    draft = resolve_instrument("000001", provider="auto")

    assert draft.company_name == "Ping An Bank"
    assert draft.exchange == "SZSE"


def test_resolve_instrument_uses_manual_name_when_providers_fail(monkeypatch):
    monkeypatch.setattr(providers, "PROVIDERS", {})

    draft = resolve_instrument("AAPL", provider="auto", name="Apple Inc.", exchange="NASDAQ")

    assert draft.market == "US"
    assert draft.exchange == "NASDAQ"
    assert draft.company_name == "Apple Inc."
