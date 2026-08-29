from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable

from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.index_futures.official import (
    BasisHistoryResult,
    OfficialMarketDataClient,
    OfficialMarketDataError,
)
from app.models.index_futures import IndexFuturesBasisSnapshot


@dataclass(frozen=True)
class BasisUpdateResult:
    trade_date: date | None
    snapshots: list[IndexFuturesBasisSnapshot]
    warnings: list[str]
    fetched: bool
    upserted: int


def _history_trade_date_count(
    session: Session,
    products: Iterable[str],
    *,
    require_pe: bool = False,
) -> int:
    selected = set(products)
    if not selected:
        return 0
    query = (
        session.query(
            IndexFuturesBasisSnapshot.trade_date,
            func.count(distinct(IndexFuturesBasisSnapshot.product)),
        )
        .filter(IndexFuturesBasisSnapshot.product.in_(selected))
    )
    if require_pe:
        query = query.filter(IndexFuturesBasisSnapshot.spot_pe.is_not(None))
    counts = query.group_by(IndexFuturesBasisSnapshot.trade_date).all()
    return sum(product_count == len(selected) for _, product_count in counts)


def _upsert_history(session: Session, result: BasisHistoryResult) -> int:
    changed = 0
    fetched_at = datetime.now(timezone.utc)
    for value in result.values:
        snapshot = (
            session.query(IndexFuturesBasisSnapshot)
            .filter_by(trade_date=value.trade_date, contract_code=value.contract_code)
            .one_or_none()
        )
        if snapshot is None:
            snapshot = IndexFuturesBasisSnapshot(
                trade_date=value.trade_date,
                contract_code=value.contract_code,
                product=value.product,
                index_code=value.index_code,
                futures_open=value.futures_open,
                futures_close=value.futures_close,
                settlement=value.settlement,
                spot_close=value.spot_close,
                spot_pe=value.spot_pe,
                expiry_date=value.expiry_date,
                days_to_expiry=value.days_to_expiry,
                volume=value.volume,
                open_interest=value.open_interest,
                discount_points=value.discount_points,
                discount_rate=value.discount_rate,
                annualized_discount_rate=value.annualized_discount_rate,
                fetched_at=fetched_at,
            )
            session.add(snapshot)
        else:
            snapshot.product = value.product
            snapshot.index_code = value.index_code
            snapshot.futures_open = value.futures_open
            snapshot.futures_close = value.futures_close
            snapshot.settlement = value.settlement
            snapshot.spot_close = value.spot_close
            snapshot.spot_pe = value.spot_pe
            snapshot.expiry_date = value.expiry_date
            snapshot.days_to_expiry = value.days_to_expiry
            snapshot.volume = value.volume
            snapshot.open_interest = value.open_interest
            snapshot.discount_points = value.discount_points
            snapshot.discount_rate = value.discount_rate
            snapshot.annualized_discount_rate = value.annualized_discount_rate
            snapshot.fetched_at = fetched_at
        changed += 1
    session.flush()
    return changed


def latest_cached_snapshots(
    session: Session,
    *,
    as_of: date,
    products: Iterable[str],
) -> tuple[date | None, list[IndexFuturesBasisSnapshot]]:
    selected = tuple(products)
    latest_date = (
        session.query(func.max(IndexFuturesBasisSnapshot.trade_date))
        .filter(IndexFuturesBasisSnapshot.trade_date <= as_of)
        .filter(IndexFuturesBasisSnapshot.product.in_(selected))
        .scalar()
    )
    if latest_date is None:
        return None, []
    rows = (
        session.query(IndexFuturesBasisSnapshot)
        .filter_by(trade_date=latest_date)
        .filter(IndexFuturesBasisSnapshot.product.in_(selected))
        .order_by(
            IndexFuturesBasisSnapshot.product,
            IndexFuturesBasisSnapshot.expiry_date,
        )
        .all()
    )
    return latest_date, rows


def update_basis_snapshots(
    session: Session,
    *,
    as_of: date,
    history_days: int = 252,
    products: Iterable[str] = ("IF", "IH", "IC", "IM"),
    client: OfficialMarketDataClient | None = None,
    force_backfill: bool = False,
    pe_history_days: int | None = None,
) -> BasisUpdateResult:
    selected = tuple(products)
    warnings: list[str] = []
    fetched = False
    upserted = 0
    existing_days = _history_trade_date_count(session, selected)
    requested_pe_days = pe_history_days if pe_history_days is not None else history_days
    existing_pe_days = _history_trade_date_count(session, selected, require_pe=True)
    requested_days = (
        max(history_days, requested_pe_days)
        if force_backfill or existing_days < history_days or existing_pe_days < requested_pe_days
        else 5
    )
    try:
        history = (client or OfficialMarketDataClient()).fetch_basis_history(
            as_of=as_of,
            history_days=requested_days,
            products=selected,
            max_months=24 if requested_days > 5 else 2,
        )
        warnings.extend(history.warnings)
        upserted = _upsert_history(session, history)
        fetched = True
    except OfficialMarketDataError as exc:
        warnings.append(f"官方股指行情更新失败，已回退数据库缓存：{exc}")

    trade_date, snapshots = latest_cached_snapshots(
        session,
        as_of=as_of,
        products=selected,
    )
    if trade_date is None:
        warnings.append("数据库中尚无可用股指期现快照。")
    elif trade_date < as_of:
        warnings.append(f"当前展示最近交易日 {trade_date.isoformat()} 的缓存数据。")
    present = {snapshot.product for snapshot in snapshots}
    missing = set(selected) - present
    if trade_date is not None and missing:
        warnings.append(f"{trade_date.isoformat()} 缺少品种：{','.join(sorted(missing))}。")
    return BasisUpdateResult(
        trade_date=trade_date,
        snapshots=snapshots,
        warnings=list(dict.fromkeys(warnings)),
        fetched=fetched,
        upserted=upserted,
    )
