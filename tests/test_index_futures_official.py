from __future__ import annotations

import io
import json
import zipfile
from datetime import date
from decimal import Decimal

import pytest

from app.index_futures.official import (
    BasisHistoryResult,
    BasisValue,
    OfficialMarketDataClient,
    OfficialMarketDataError,
    parse_cffex_contract_xml,
    parse_cffex_monthly_zip,
    parse_csindex_history,
)
from app.index_futures.service import update_basis_snapshots
from app.models.index_futures import IndexFuturesBasisSnapshot


def _monthly_zip() -> bytes:
    csv_text = "\n".join(
        [
            "合约代码,今开盘,最高价,最低价,成交量,成交金额,持仓量,持仓变化,今收盘,今结算,前结算,涨跌1,涨跌2,Delta",
            "IF2608,4700,4720,4680,123,1,456,2,4690,4692,4688,2,4,--",
            "IH2608,--,3000,2900,10,1,20,2,2950,2951,2940,10,11,--",
            "T2609,100,101,99,10,1,20,2,100,100,99,1,1,--",
        ]
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("20260807_1.csv", csv_text.encode("gb2312"))
        archive.comment = b"fixture-padding" * 100
    return buffer.getvalue()


def _basis(contract: str = "IF2608") -> BasisValue:
    return BasisValue(
        trade_date=date(2026, 8, 7),
        product="IF",
        contract_code=contract,
        index_code="000300",
        futures_open=Decimal("4700"),
        futures_close=Decimal("4690"),
        settlement=Decimal("4692"),
        spot_close=Decimal("4710"),
        expiry_date=date(2026, 8, 21),
        days_to_expiry=14,
        volume=123,
        open_interest=456,
        discount_points=Decimal("20"),
        discount_rate=Decimal("20") / Decimal("4710"),
        annualized_discount_rate=(Decimal("20") / Decimal("4710")) * 365 / 14,
    )


def test_parse_cffex_gb2312_zip_validates_contract_and_prices():
    quotes = parse_cffex_monthly_zip(_monthly_zip())

    assert len(quotes) == 1
    assert quotes[0].contract_code == "IF2608"
    assert quotes[0].trade_date == date(2026, 8, 7)
    assert quotes[0].futures_close == Decimal("4690")
    assert quotes[0].open_interest == 456


def test_parse_cffex_contract_xml_and_csindex_json():
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <ROOT><INDEX><INSTRUMENT_ID>IF2608</INSTRUMENT_ID>
    <PRODUCT_ID>IF</PRODUCT_ID><END_TRADING_DAY>20260821</END_TRADING_DAY>
    </INDEX></ROOT>""" + b" " * 100
    assert parse_cffex_contract_xml(xml) == {"IF2608": date(2026, 8, 21)}

    payload = json.dumps(
        {
            "code": "200",
            "data": [
                {"tradeDate": "20260807", "indexCode": "000300", "close": 4710.25},
                {"tradeDate": "20260808", "indexCode": "000905", "close": 7000},
            ],
        }
    ).encode()
    assert parse_csindex_history(payload, "000300") == {
        date(2026, 8, 7): Decimal("4710.25")
    }


class _Response:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content


class _RetrySession:
    def __init__(self):
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return _Response(503, b"unavailable")
        return _Response(200, _monthly_zip())


def test_official_client_retries_and_rejects_invalid_payload():
    transport = _RetrySession()
    client = OfficialMarketDataClient(session=transport, max_retries=1)

    assert len(client.fetch_month(date(2026, 8, 1))) == 1
    assert transport.calls == 2
    with pytest.raises(OfficialMarketDataError):
        parse_cffex_monthly_zip(b"not-a-zip")


class _HistoryClient:
    def fetch_basis_history(self, **kwargs):
        return BasisHistoryResult(values=[_basis()], warnings=["fixture warning"])


class _FailingClient:
    def fetch_basis_history(self, **kwargs):
        raise OfficialMarketDataError("network down")


def test_basis_upsert_is_idempotent_and_network_failure_uses_cache(session):
    first = update_basis_snapshots(
        session,
        as_of=date(2026, 8, 10),
        history_days=252,
        products=["IF"],
        client=_HistoryClient(),
    )
    second = update_basis_snapshots(
        session,
        as_of=date(2026, 8, 10),
        history_days=252,
        products=["IF"],
        client=_HistoryClient(),
    )
    cached = update_basis_snapshots(
        session,
        as_of=date(2026, 8, 10),
        history_days=252,
        products=["IF"],
        client=_FailingClient(),
    )

    assert first.trade_date == second.trade_date == cached.trade_date == date(2026, 8, 7)
    assert session.query(IndexFuturesBasisSnapshot).count() == 1
    assert cached.fetched is False
    assert "回退数据库缓存" in " ".join(cached.warnings)
