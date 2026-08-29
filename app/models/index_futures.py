from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IndexFuturesBasisSnapshot(Base):
    __tablename__ = "index_futures_basis_snapshot"
    __table_args__ = (
        UniqueConstraint("trade_date", "contract_code", name="uq_index_futures_basis_date_contract"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    product: Mapped[str] = mapped_column(String(2), index=True)
    contract_code: Mapped[str] = mapped_column(String(10))
    index_code: Mapped[str] = mapped_column(String(6))
    futures_open: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    futures_close: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    settlement: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    spot_close: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    spot_pe: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    expiry_date: Mapped[date] = mapped_column(Date)
    days_to_expiry: Mapped[int] = mapped_column(Integer)
    volume: Mapped[int] = mapped_column(BigInteger)
    open_interest: Mapped[int] = mapped_column(BigInteger)
    discount_points: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    discount_rate: Mapped[Decimal] = mapped_column(Numeric(18, 10))
    annualized_discount_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 10), nullable=True
    )
    source_name: Mapped[str] = mapped_column(String(50), default="cffex+csindex")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, onupdate=_utc_now)


class IndexFuturesPaperPortfolio(Base):
    __tablename__ = "index_futures_paper_portfolio"

    product: Mapped[str] = mapped_column(String(2), primary_key=True)
    index_code: Mapped[str] = mapped_column(String(6))
    multiplier: Mapped[int] = mapped_column(Integer)
    initial_nav: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    nav: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    current_contract: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 10), default=Decimal("0"))
    pending_contract: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    pending_signal_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    pending_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    pending_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 10), nullable=True)
    benchmark_start_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    cumulative_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6), default=Decimal("0"))
    roll_count: Mapped[int] = mapped_column(Integer, default=0)
    peak_nav: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    max_drawdown: Mapped[Decimal] = mapped_column(Numeric(18, 10), default=Decimal("0"))
    last_processed_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, onupdate=_utc_now)


class IndexFuturesPaperNav(Base):
    __tablename__ = "index_futures_paper_nav"
    __table_args__ = (
        UniqueConstraint("trade_date", "product", name="uq_index_futures_paper_nav_date_product"),
    )

    nav_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    product: Mapped[str] = mapped_column(String(2), index=True)
    contract_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    nav: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    daily_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    daily_return: Mapped[Decimal] = mapped_column(Numeric(18, 10))
    benchmark_close: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    benchmark_nav: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    position_notional: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    cumulative_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    drawdown: Mapped[Decimal] = mapped_column(Numeric(18, 10))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class IndexFuturesPaperTrade(Base):
    __tablename__ = "index_futures_paper_trade"

    trade_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    product: Mapped[str] = mapped_column(String(2), index=True)
    signal_date: Mapped[date] = mapped_column(Date)
    execution_date: Mapped[date] = mapped_column(Date, index=True)
    from_contract: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    to_contract: Mapped[str] = mapped_column(String(10))
    from_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    to_price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    quantity_before: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    quantity_after: Mapped[Decimal] = mapped_column(Numeric(24, 10))
    notional: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    transaction_cost: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    reason: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class IndexFuturesMarketCommentary(Base):
    __tablename__ = "index_futures_market_commentary"
    __table_args__ = (
        UniqueConstraint("trade_date", name="uq_index_futures_commentary_trade_date"),
    )

    commentary_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(20), default="v1")
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    overall_summary: Mapped[str] = mapped_column(Text)
    product_commentaries: Mapped[str] = mapped_column(Text)
    portfolio_observation: Mapped[str] = mapped_column(Text)
    risk_flags: Mapped[str] = mapped_column(Text)
    used_llm: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
