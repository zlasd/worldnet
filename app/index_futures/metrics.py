from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Sequence

from sqlalchemy.orm import Session

from app.digests.config import PaperStrategyConfig
from app.index_futures.constants import PRODUCT_SPECS, RESEARCH_DISCLAIMER
from app.index_futures.paper import net_annualized_score
from app.models.index_futures import (
    IndexFuturesBasisSnapshot,
    IndexFuturesPaperPortfolio,
)


@dataclass(frozen=True)
class PercentileStat:
    lookback: int
    sample_size: int
    percentile: Decimal | None


@dataclass(frozen=True)
class CurvePoint:
    product: str
    maturity_rank: int
    contract_code: str
    expiry_date: date
    days_to_expiry: int
    futures_close: Decimal
    spot_close: Decimal
    discount_points: Decimal
    discount_rate: Decimal
    annualized_discount_rate: Decimal | None
    net_annualized_score: Decimal | None
    discount_rate_change_1d: Decimal | None
    discount_rate_change_5d: Decimal | None
    volume: int
    open_interest: int


@dataclass(frozen=True)
class ProductMetric:
    product: str
    product_name: str
    index_name: str
    best_net_annualized_score: Decimal | None
    percentiles: tuple[PercentileStat, ...]


@dataclass(frozen=True)
class PortfolioMetric:
    product: str
    current_contract: str | None
    pending_contract: str | None
    pending_signal_date: date | None
    pending_reason: str | None
    nav: Decimal
    cumulative_return: Decimal
    benchmark_return: Decimal
    excess_return: Decimal
    max_drawdown: Decimal
    roll_count: int
    cumulative_cost: Decimal


@dataclass(frozen=True)
class MarketMetrics:
    trade_date: date
    curves: tuple[CurvePoint, ...]
    products: tuple[ProductMetric, ...]
    portfolios: tuple[PortfolioMetric, ...]
    warnings: tuple[str, ...]
    disclaimer: str = RESEARCH_DISCLAIMER

    def prompt_payload(self) -> dict[str, Any]:
        return _json_ready(
            {
                "trade_date": self.trade_date,
                "curves": [asdict(point) for point in self.curves],
                "portfolios": [asdict(portfolio) for portfolio in self.portfolios],
                "warnings": self.warnings,
                "disclaimer": self.disclaimer,
            }
        )


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (date, Decimal)):
        return str(value)
    return value


def _rows_for_date(
    session: Session,
    product: str,
    trade_date: date,
) -> list[IndexFuturesBasisSnapshot]:
    return (
        session.query(IndexFuturesBasisSnapshot)
        .filter_by(product=product, trade_date=trade_date)
        .order_by(IndexFuturesBasisSnapshot.expiry_date)
        .all()
    )


def _best_score(
    rows: Sequence[IndexFuturesBasisSnapshot],
    config: PaperStrategyConfig,
) -> Decimal | None:
    scores = [
        score
        for row in rows
        if row.days_to_expiry >= config.minimum_days_to_expiry
        and row.volume > 0
        and row.open_interest > 0
        and (
            score := net_annualized_score(
                row,
                Decimal(str(config.transaction_cost_bps)),
            )
        )
        is not None
    ]
    return max(scores) if scores else None


def _percentile(values: Sequence[Decimal], current: Decimal | None, lookback: int) -> PercentileStat:
    sample = list(values[-lookback:])
    if current is None or not sample:
        return PercentileStat(lookback, len(sample), None)
    rank = Decimal(sum(value <= current for value in sample)) / Decimal(len(sample))
    return PercentileStat(lookback, len(sample), rank)


def _portfolio_metric(
    session: Session,
    product: str,
    config: PaperStrategyConfig,
) -> PortfolioMetric:
    portfolio = session.get(IndexFuturesPaperPortfolio, product)
    initial_nav = Decimal(str(config.initial_nav))
    if portfolio is None:
        return PortfolioMetric(
            product=product,
            current_contract=None,
            pending_contract=None,
            pending_signal_date=None,
            pending_reason=None,
            nav=initial_nav,
            cumulative_return=Decimal("0"),
            benchmark_return=Decimal("0"),
            excess_return=Decimal("0"),
            max_drawdown=Decimal("0"),
            roll_count=0,
            cumulative_cost=Decimal("0"),
        )
    nav = Decimal(portfolio.nav)
    initial_nav = Decimal(portfolio.initial_nav)
    last_nav = None
    if portfolio.last_processed_date is not None:
        from app.models.index_futures import IndexFuturesPaperNav

        last_nav = (
            session.query(IndexFuturesPaperNav)
            .filter_by(product=product, trade_date=portfolio.last_processed_date)
            .one_or_none()
        )
    benchmark_return = (
        Decimal(last_nav.benchmark_nav) / initial_nav - Decimal("1")
        if last_nav is not None
        else Decimal("0")
    )
    cumulative_return = nav / initial_nav - Decimal("1")
    return PortfolioMetric(
        product=product,
        current_contract=portfolio.current_contract,
        pending_contract=portfolio.pending_contract,
        pending_signal_date=portfolio.pending_signal_date,
        pending_reason=portfolio.pending_reason,
        nav=nav,
        cumulative_return=cumulative_return,
        benchmark_return=benchmark_return,
        excess_return=cumulative_return - benchmark_return,
        max_drawdown=Decimal(portfolio.max_drawdown),
        roll_count=portfolio.roll_count,
        cumulative_cost=Decimal(portfolio.cumulative_cost),
    )


def build_market_metrics(
    session: Session,
    *,
    trade_date: date,
    config: PaperStrategyConfig,
    products: Iterable[str] = ("IF", "IH", "IC", "IM"),
    warnings: Iterable[str] = (),
) -> MarketMetrics:
    selected = tuple(product for product in products if product in PRODUCT_SPECS)
    all_warnings = list(warnings)
    curves: list[CurvePoint] = []
    product_metrics: list[ProductMetric] = []
    portfolio_metrics: list[PortfolioMetric] = []

    for product in selected:
        trade_dates = [
            row[0]
            for row in (
                session.query(IndexFuturesBasisSnapshot.trade_date)
                .filter_by(product=product)
                .filter(IndexFuturesBasisSnapshot.trade_date <= trade_date)
                .distinct()
                .order_by(IndexFuturesBasisSnapshot.trade_date)
                .all()
            )
        ]
        current_rows = _rows_for_date(session, product, trade_date)
        if not current_rows:
            all_warnings.append(f"{trade_date.isoformat()} 缺少 {product} 期限结构。")
        elif len(current_rows) < 4:
            all_warnings.append(f"{product} 当前仅有 {len(current_rows)}/4 个期限。")
        history_rows = {
            historical_date: _rows_for_date(session, product, historical_date)
            for historical_date in trade_dates
        }
        daily_best = [
            score
            for historical_date in trade_dates
            if (score := _best_score(history_rows[historical_date], config)) is not None
        ]
        current_best = _best_score(current_rows, config)
        previous_rows = history_rows.get(trade_dates[-2], []) if len(trade_dates) >= 2 else []
        five_day_rows = history_rows.get(trade_dates[-6], []) if len(trade_dates) >= 6 else []
        for rank, row in enumerate(current_rows, start=1):
            previous = previous_rows[rank - 1] if len(previous_rows) >= rank else None
            five_day = five_day_rows[rank - 1] if len(five_day_rows) >= rank else None
            curves.append(
                CurvePoint(
                    product=product,
                    maturity_rank=rank,
                    contract_code=row.contract_code,
                    expiry_date=row.expiry_date,
                    days_to_expiry=row.days_to_expiry,
                    futures_close=Decimal(row.futures_close),
                    spot_close=Decimal(row.spot_close),
                    discount_points=Decimal(row.discount_points),
                    discount_rate=Decimal(row.discount_rate),
                    annualized_discount_rate=(
                        Decimal(row.annualized_discount_rate)
                        if row.annualized_discount_rate is not None
                        else None
                    ),
                    net_annualized_score=net_annualized_score(
                        row,
                        Decimal(str(config.transaction_cost_bps)),
                    ),
                    discount_rate_change_1d=(
                        Decimal(row.discount_rate) - Decimal(previous.discount_rate)
                        if previous is not None
                        else None
                    ),
                    discount_rate_change_5d=(
                        Decimal(row.discount_rate) - Decimal(five_day.discount_rate)
                        if five_day is not None
                        else None
                    ),
                    volume=row.volume,
                    open_interest=row.open_interest,
                )
            )
        spec = PRODUCT_SPECS[product]
        percentiles = tuple(_percentile(daily_best, current_best, n) for n in (20, 60, 252))
        product_metrics.append(
            ProductMetric(
                product=product,
                product_name=spec.name,
                index_name=spec.index_name,
                best_net_annualized_score=current_best,
                percentiles=percentiles,
            )
        )
        portfolio_metrics.append(_portfolio_metric(session, product, config))

    return MarketMetrics(
        trade_date=trade_date,
        curves=tuple(curves),
        products=tuple(product_metrics),
        portfolios=tuple(portfolio_metrics),
        warnings=tuple(dict.fromkeys(all_warnings)),
    )
