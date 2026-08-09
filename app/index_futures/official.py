from __future__ import annotations

import csv
import io
import json
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from xml.etree import ElementTree

from curl_cffi import requests

from app.core.config import settings
from app.index_futures.constants import PRODUCT_SPECS

CFFEX_ARCHIVE_ROOT = "http://www.cffex.com.cn/sj/historysj"
CFFEX_CONTRACT_ROOT = "http://www.cffex.com.cn/sj/jycs"
CSINDEX_PERFORMANCE_URL = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
CONTRACT_PATTERN = re.compile(r"^(IF|IH|IC|IM)\d{4}$")
ARCHIVE_MEMBER_PATTERN = re.compile(r"^(\d{8})_1\.csv$")


class OfficialMarketDataError(RuntimeError):
    """The official endpoint returned unusable or inconsistent market data."""


@dataclass(frozen=True)
class FuturesQuote:
    trade_date: date
    product: str
    contract_code: str
    futures_open: Decimal
    futures_close: Decimal
    settlement: Decimal | None
    volume: int
    open_interest: int


@dataclass(frozen=True)
class BasisValue:
    trade_date: date
    product: str
    contract_code: str
    index_code: str
    futures_open: Decimal
    futures_close: Decimal
    settlement: Decimal | None
    spot_close: Decimal
    expiry_date: date
    days_to_expiry: int
    volume: int
    open_interest: int
    discount_points: Decimal
    discount_rate: Decimal
    annualized_discount_rate: Decimal | None


@dataclass(frozen=True)
class BasisHistoryResult:
    values: list[BasisValue]
    warnings: list[str]

    @property
    def trade_dates(self) -> list[date]:
        return sorted({value.trade_date for value in self.values})


def _decimal(value: Any, *, positive: bool = False) -> Decimal:
    text = str(value or "").strip().replace(",", "")
    if text in {"", "-", "--", "None", "null"}:
        raise ValueError("missing_numeric_value")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid_numeric_value:{text}") from exc
    if positive and number <= 0:
        raise ValueError(f"non_positive_numeric_value:{text}")
    return number


def _optional_decimal(value: Any) -> Decimal | None:
    try:
        return _decimal(value)
    except ValueError:
        return None


def _integer(value: Any) -> int:
    number = _decimal(value)
    if number < 0:
        raise ValueError("negative_integer_value")
    return int(number)


def _clean_row(row: dict[str | None, str | None]) -> dict[str, str]:
    return {
        str(key or "").replace("\ufeff", "").strip(): str(value or "").strip()
        for key, value in row.items()
        if key is not None
    }


def parse_cffex_monthly_zip(content: bytes) -> list[FuturesQuote]:
    if len(content) < 1_000 or len(content) > 30_000_000 or not content.startswith(b"PK"):
        raise OfficialMarketDataError("cffex_archive_invalid_payload")
    quotes: list[FuturesQuote] = []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = [name for name in archive.namelist() if ARCHIVE_MEMBER_PATTERN.match(name)]
            if not members:
                raise OfficialMarketDataError("cffex_archive_missing_daily_csv")
            for member in sorted(members):
                info = archive.getinfo(member)
                if info.file_size <= 0 or info.file_size > 5_000_000:
                    raise OfficialMarketDataError("cffex_archive_invalid_csv_size")
                match = ARCHIVE_MEMBER_PATTERN.match(member)
                assert match is not None
                member_date = datetime.strptime(match.group(1), "%Y%m%d").date()
                text = archive.read(member).decode("gb18030")
                reader = csv.DictReader(io.StringIO(text))
                for raw_row in reader:
                    row = _clean_row(raw_row)
                    contract = row.get("合约代码", "").replace(" ", "").upper()
                    match_contract = CONTRACT_PATTERN.fullmatch(contract)
                    if not match_contract:
                        continue
                    try:
                        quotes.append(
                            FuturesQuote(
                                trade_date=member_date,
                                product=match_contract.group(1),
                                contract_code=contract,
                                futures_open=_decimal(row.get("今开盘"), positive=True),
                                futures_close=_decimal(row.get("今收盘"), positive=True),
                                settlement=_optional_decimal(row.get("今结算")),
                                volume=_integer(row.get("成交量")),
                                open_interest=_integer(row.get("持仓量")),
                            )
                        )
                    except ValueError:
                        continue
    except (zipfile.BadZipFile, UnicodeDecodeError, KeyError) as exc:
        raise OfficialMarketDataError("cffex_archive_parse_failed") from exc
    if not quotes:
        raise OfficialMarketDataError("cffex_archive_no_index_futures")
    return quotes


def _element_values(element: ElementTree.Element) -> dict[str, str]:
    return {
        child.tag.rsplit("}", 1)[-1].upper(): (child.text or "").strip()
        for child in list(element)
    }


def parse_cffex_contract_xml(content: bytes) -> dict[str, date]:
    if len(content) < 100 or len(content) > 5_000_000 or b"<" not in content[:100]:
        raise OfficialMarketDataError("cffex_contract_invalid_payload")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise OfficialMarketDataError("cffex_contract_parse_failed") from exc
    expiries: dict[str, date] = {}
    for element in root.iter():
        values = _element_values(element)
        contract = values.get("INSTRUMENT_ID", "").replace(" ", "").upper()
        if not CONTRACT_PATTERN.fullmatch(contract):
            continue
        raw_expiry = values.get("END_TRADING_DAY", "")
        try:
            expiry = datetime.strptime(raw_expiry.replace("-", ""), "%Y%m%d").date()
        except ValueError:
            continue
        expiries[contract] = expiry
    if not expiries:
        raise OfficialMarketDataError("cffex_contract_no_index_futures")
    return expiries


def parse_csindex_history(payload: bytes, index_code: str) -> dict[date, Decimal]:
    if len(payload) < 20 or len(payload) > 10_000_000:
        raise OfficialMarketDataError("csindex_invalid_payload")
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficialMarketDataError("csindex_invalid_json") from exc
    if not isinstance(document, dict) or str(document.get("code")) != "200":
        raise OfficialMarketDataError("csindex_unsuccessful_response")
    rows = document.get("data")
    if not isinstance(rows, list):
        raise OfficialMarketDataError("csindex_data_not_list")
    history: dict[date, Decimal] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        returned_code = str(row.get("indexCode") or row.get("indexcode") or index_code)
        if returned_code != index_code:
            continue
        raw_date = str(row.get("tradeDate") or "").strip().replace("-", "")
        try:
            trade_date = datetime.strptime(raw_date, "%Y%m%d").date()
            close = _decimal(row.get("close"), positive=True)
        except ValueError:
            continue
        history[trade_date] = close
    if not history:
        raise OfficialMarketDataError(f"csindex_no_prices:{index_code}")
    return history


def _previous_month(value: date) -> date:
    return date(value.year - 1, 12, 1) if value.month == 1 else date(value.year, value.month - 1, 1)


class OfficialMarketDataClient:
    def __init__(
        self,
        *,
        session: Any | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.session = session or requests.Session(impersonate="chrome")
        self.timeout_seconds = timeout_seconds or settings.official_market_data_timeout_seconds
        self.max_retries = (
            settings.official_market_data_max_retries if max_retries is None else max_retries
        )

    def _get(self, url: str, *, params: dict[str, str] | None = None) -> bytes:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout_seconds,
                    headers={
                        "Accept": "application/json,text/xml,application/zip,*/*",
                        "Referer": "https://www.cffex.com.cn/",
                    },
                )
                if response.status_code != 200:
                    raise OfficialMarketDataError(f"official_http_{response.status_code}")
                content = bytes(response.content)
                if not content:
                    raise OfficialMarketDataError("official_empty_response")
                return content
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(0.25 * (attempt + 1))
        raise OfficialMarketDataError(str(last_error or "official_request_failed")) from last_error

    def fetch_month(self, month: date) -> list[FuturesQuote]:
        key = month.strftime("%Y%m")
        url = f"{CFFEX_ARCHIVE_ROOT}/{key}/zip/{key}.zip"
        return parse_cffex_monthly_zip(self._get(url))

    def fetch_contract_expiries(self, trade_date: date) -> dict[str, date]:
        url = (
            f"{CFFEX_CONTRACT_ROOT}/{trade_date:%Y%m}/{trade_date:%d}/index.xml"
        )
        return parse_cffex_contract_xml(self._get(url))

    def fetch_index_history(
        self,
        index_code: str,
        start_date: date,
        end_date: date,
    ) -> dict[date, Decimal]:
        content = self._get(
            CSINDEX_PERFORMANCE_URL,
            params={
                "indexCode": index_code,
                "startDate": start_date.strftime("%Y%m%d"),
                "endDate": end_date.strftime("%Y%m%d"),
            },
        )
        return parse_csindex_history(content, index_code)

    def fetch_basis_history(
        self,
        *,
        as_of: date,
        history_days: int,
        products: Iterable[str],
        max_months: int = 24,
    ) -> BasisHistoryResult:
        selected_products = tuple(product for product in products if product in PRODUCT_SPECS)
        if not selected_products:
            return BasisHistoryResult(values=[], warnings=["未配置有效股指期货品种。"])

        warnings: list[str] = []
        quotes: list[FuturesQuote] = []
        month = as_of.replace(day=1)
        target_buffer = history_days + 20
        for _ in range(max_months):
            try:
                month_quotes = [
                    quote
                    for quote in self.fetch_month(month)
                    if quote.trade_date <= as_of and quote.product in selected_products
                ]
                quotes.extend(month_quotes)
            except OfficialMarketDataError as exc:
                warnings.append(f"中金所 {month:%Y-%m} 月度行情不可用：{exc}")
            product_dates = {
                product: {quote.trade_date for quote in quotes if quote.product == product}
                for product in selected_products
            }
            common_dates = set.intersection(*(dates for dates in product_dates.values()))
            if len(common_dates) >= target_buffer:
                break
            month = _previous_month(month)

        if not quotes:
            raise OfficialMarketDataError("cffex_history_unavailable")
        product_dates = {
            product: {quote.trade_date for quote in quotes if quote.product == product}
            for product in selected_products
        }
        common_dates = sorted(set.intersection(*(dates for dates in product_dates.values())))
        if not common_dates:
            raise OfficialMarketDataError("cffex_no_common_trade_date")
        candidate_dates = set(common_dates[-target_buffer:])
        quotes = [quote for quote in quotes if quote.trade_date in candidate_dates]
        latest_date = max(candidate_dates)

        observed_expiries: dict[str, date] = {}
        for quote in quotes:
            observed_expiries[quote.contract_code] = max(
                quote.trade_date,
                observed_expiries.get(quote.contract_code, quote.trade_date),
            )
        try:
            official_expiries = self.fetch_contract_expiries(latest_date)
        except OfficialMarketDataError as exc:
            official_expiries = {}
            warnings.append(f"中金所在市合约到期日不可用：{exc}")
        expiries = {**observed_expiries, **official_expiries}

        start_date = min(candidate_dates)
        spot_histories: dict[str, dict[date, Decimal]] = {}
        for product in selected_products:
            spec = PRODUCT_SPECS[product]
            try:
                spot_histories[product] = self.fetch_index_history(
                    spec.index_code,
                    start_date,
                    latest_date,
                )
            except OfficialMarketDataError as exc:
                warnings.append(f"中证指数 {spec.index_code} 行情不可用：{exc}")

        values: list[BasisValue] = []
        for quote in quotes:
            spot_close = spot_histories.get(quote.product, {}).get(quote.trade_date)
            expiry = expiries.get(quote.contract_code)
            if spot_close is None or expiry is None or expiry < quote.trade_date:
                continue
            # When the XML is unavailable, the last observed date of an active contract is not
            # an official expiry. Keep expired history but omit unresolved latest-date contracts.
            if (
                not official_expiries
                and expiry == latest_date
                and quote.trade_date == latest_date
            ):
                continue
            days_to_expiry = (expiry - quote.trade_date).days
            discount_points = spot_close - quote.futures_close
            discount_rate = discount_points / spot_close
            annualized = (
                discount_rate * Decimal(365) / Decimal(days_to_expiry)
                if days_to_expiry > 0
                else None
            )
            values.append(
                BasisValue(
                    trade_date=quote.trade_date,
                    product=quote.product,
                    contract_code=quote.contract_code,
                    index_code=PRODUCT_SPECS[quote.product].index_code,
                    futures_open=quote.futures_open,
                    futures_close=quote.futures_close,
                    settlement=quote.settlement,
                    spot_close=spot_close,
                    expiry_date=expiry,
                    days_to_expiry=days_to_expiry,
                    volume=quote.volume,
                    open_interest=quote.open_interest,
                    discount_points=discount_points,
                    discount_rate=discount_rate,
                    annualized_discount_rate=annualized,
                )
            )

        valid_products_by_date: dict[date, set[str]] = {}
        for value in values:
            valid_products_by_date.setdefault(value.trade_date, set()).add(value.product)
        valid_common_dates = sorted(
            trade_date
            for trade_date, present in valid_products_by_date.items()
            if present == set(selected_products)
        )
        keep_dates = set(valid_common_dates[-history_days:])
        # Keep a newer partial day instead of hiding valid products merely because one official
        # index endpoint is temporarily missing. Historical sufficiency still counts common days.
        if valid_products_by_date:
            latest_valid_date = max(valid_products_by_date)
            if not keep_dates or latest_valid_date > max(keep_dates):
                keep_dates.add(latest_valid_date)
        values = [value for value in values if value.trade_date in keep_dates]
        if len(keep_dates) < history_days:
            warnings.append(f"共同交易日历史不足：{len(keep_dates)}/{history_days}。")
        if values:
            latest_kept = max(value.trade_date for value in values)
            present = {value.product for value in values if value.trade_date == latest_kept}
            missing = set(selected_products) - present
            if missing:
                warnings.append(f"最新交易日缺少品种：{','.join(sorted(missing))}。")
        return BasisHistoryResult(values=values, warnings=warnings)
