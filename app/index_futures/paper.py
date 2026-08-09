from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy.orm import Session

from app.digests.config import PaperStrategyConfig
from app.index_futures.constants import PRODUCT_SPECS
from app.models.index_futures import (
    IndexFuturesBasisSnapshot,
    IndexFuturesPaperNav,
    IndexFuturesPaperPortfolio,
    IndexFuturesPaperTrade,
)

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class RollSignal:
    contract_code: str
    net_annualized_score: Decimal
    reason: str


@dataclass
class PaperStrategyUpdateResult:
    processed_dates: set[date] = field(default_factory=set)
    trades: int = 0
    warnings: list[str] = field(default_factory=list)


def net_annualized_score(
    snapshot: IndexFuturesBasisSnapshot,
    transaction_cost_bps: Decimal,
) -> Decimal | None:
    if snapshot.days_to_expiry <= 0:
        return None
    cost_rate = transaction_cost_bps / Decimal("10000")
    return (
        (Decimal(snapshot.discount_rate) - cost_rate)
        * Decimal(365)
        / Decimal(snapshot.days_to_expiry)
    )


def select_roll_signal(
    snapshots: Sequence[IndexFuturesBasisSnapshot],
    *,
    current_contract: str | None,
    minimum_days_to_expiry: int,
    transaction_cost_bps: Decimal,
    switch_threshold_annualized: Decimal,
) -> RollSignal | None:
    eligible: list[tuple[IndexFuturesBasisSnapshot, Decimal]] = []
    for snapshot in snapshots:
        if (
            snapshot.days_to_expiry < minimum_days_to_expiry
            or snapshot.volume <= 0
            or snapshot.open_interest <= 0
        ):
            continue
        score = net_annualized_score(snapshot, transaction_cost_bps)
        if score is not None:
            eligible.append((snapshot, score))
    if not eligible:
        return None

    best, best_score = max(eligible, key=lambda item: (item[1], item[0].contract_code))
    if current_contract is None:
        return RollSignal(best.contract_code, best_score, "initial_selection")

    current = next(
        (snapshot for snapshot in snapshots if snapshot.contract_code == current_contract),
        None,
    )
    if current is None or current.days_to_expiry < minimum_days_to_expiry:
        if best.contract_code == current_contract:
            return None
        return RollSignal(best.contract_code, best_score, "forced_expiry_roll")
    if best.contract_code == current_contract:
        return None
    current_score = current.annualized_discount_rate
    if current_score is None:
        return RollSignal(best.contract_code, best_score, "score_improvement")
    if best_score >= Decimal(current_score) + switch_threshold_annualized:
        return RollSignal(best.contract_code, best_score, "score_improvement")
    return None


def _portfolio(
    session: Session,
    product: str,
    config: PaperStrategyConfig,
) -> IndexFuturesPaperPortfolio:
    portfolio = session.get(IndexFuturesPaperPortfolio, product)
    if portfolio is not None:
        return portfolio
    initial_nav = Decimal(str(config.initial_nav))
    spec = PRODUCT_SPECS[product]
    portfolio = IndexFuturesPaperPortfolio(
        product=product,
        index_code=spec.index_code,
        multiplier=spec.multiplier,
        initial_nav=initial_nav,
        nav=initial_nav,
        quantity=ZERO,
        cumulative_cost=ZERO,
        roll_count=0,
        peak_nav=initial_nav,
        max_drawdown=ZERO,
    )
    session.add(portfolio)
    session.flush()
    return portfolio


def _previous_snapshot(
    session: Session,
    product: str,
    contract_code: str,
    trade_date: date,
) -> IndexFuturesBasisSnapshot | None:
    return (
        session.query(IndexFuturesBasisSnapshot)
        .filter_by(product=product, contract_code=contract_code)
        .filter(IndexFuturesBasisSnapshot.trade_date < trade_date)
        .order_by(IndexFuturesBasisSnapshot.trade_date.desc())
        .first()
    )


def _execute_pending(
    session: Session,
    portfolio: IndexFuturesPaperPortfolio,
    rows_by_code: dict[str, IndexFuturesBasisSnapshot],
    trade_date: date,
    config: PaperStrategyConfig,
    warnings: list[str],
) -> tuple[Decimal, bool]:
    """Execute a prior-close signal at today's open and return today's total PnL."""
    if (
        portfolio.pending_contract is None
        or portfolio.pending_signal_date is None
        or portfolio.pending_signal_date >= trade_date
    ):
        return ZERO, False
    target = rows_by_code.get(portfolio.pending_contract)
    current = rows_by_code.get(portfolio.current_contract or "")
    if target is None or (portfolio.current_contract is not None and current is None):
        warnings.append(
            f"{portfolio.product} {trade_date.isoformat()} 目标或原合约开盘价缺失，模拟换月延后。"
        )
        return ZERO, False

    prior_nav = Decimal(portfolio.nav)
    multiplier = Decimal(portfolio.multiplier)
    quantity_before = Decimal(portfolio.quantity)
    pre_execution_pnl = ZERO
    from_price: Decimal | None = None
    if portfolio.current_contract is not None and current is not None:
        previous = _previous_snapshot(
            session,
            portfolio.product,
            portfolio.current_contract,
            trade_date,
        )
        if previous is None:
            warnings.append(
                f"{portfolio.product} {trade_date.isoformat()} 缺少原合约前收盘，模拟换月延后。"
            )
            return ZERO, False
        from_price = Decimal(current.futures_open)
        pre_execution_pnl = (
            quantity_before
            * multiplier
            * (from_price - Decimal(previous.futures_close))
        )

    nav_at_open = prior_nav + pre_execution_pnl
    cost_rate = Decimal(str(config.transaction_cost_bps)) / Decimal("10000")
    transaction_cost = nav_at_open * cost_rate
    nav_after_cost = nav_at_open - transaction_cost
    to_price = Decimal(target.futures_open)
    quantity_after = nav_after_cost / (to_price * multiplier)
    close_pnl = quantity_after * multiplier * (Decimal(target.futures_close) - to_price)
    portfolio.nav = nav_after_cost + close_pnl
    old_contract = portfolio.current_contract
    portfolio.current_contract = target.contract_code
    portfolio.quantity = quantity_after
    portfolio.cumulative_cost = Decimal(portfolio.cumulative_cost) + transaction_cost
    if old_contract is not None:
        portfolio.roll_count += 1

    session.add(
        IndexFuturesPaperTrade(
            product=portfolio.product,
            signal_date=portfolio.pending_signal_date,
            execution_date=trade_date,
            from_contract=old_contract,
            to_contract=target.contract_code,
            from_price=from_price,
            to_price=to_price,
            quantity_before=quantity_before,
            quantity_after=quantity_after,
            notional=quantity_after * multiplier * to_price,
            transaction_cost=transaction_cost,
            reason=portfolio.pending_reason or "scheduled_roll",
        )
    )
    portfolio.pending_contract = None
    portfolio.pending_signal_date = None
    portfolio.pending_reason = None
    portfolio.pending_score = None
    return Decimal(portfolio.nav) - prior_nav, True


def _mark_existing_position(
    session: Session,
    portfolio: IndexFuturesPaperPortfolio,
    rows_by_code: dict[str, IndexFuturesBasisSnapshot],
    trade_date: date,
    warnings: list[str],
) -> Decimal:
    if portfolio.current_contract is None:
        return ZERO
    current = rows_by_code.get(portfolio.current_contract)
    if current is None:
        warnings.append(
            f"{portfolio.product} {trade_date.isoformat()} 持仓合约行情缺失，NAV 未推进。"
        )
        return ZERO
    previous = _previous_snapshot(
        session,
        portfolio.product,
        portfolio.current_contract,
        trade_date,
    )
    if previous is None:
        warnings.append(
            f"{portfolio.product} {trade_date.isoformat()} 缺少前收盘，NAV 未推进。"
        )
        return ZERO
    pnl = (
        Decimal(portfolio.quantity)
        * Decimal(portfolio.multiplier)
        * (Decimal(current.futures_close) - Decimal(previous.futures_close))
    )
    portfolio.nav = Decimal(portfolio.nav) + pnl
    return pnl


def _record_nav(
    session: Session,
    portfolio: IndexFuturesPaperPortfolio,
    snapshots: Sequence[IndexFuturesBasisSnapshot],
    trade_date: date,
    prior_nav: Decimal,
) -> None:
    benchmark_close = Decimal(snapshots[0].spot_close)
    if portfolio.benchmark_start_close is None:
        portfolio.benchmark_start_close = benchmark_close
    benchmark_nav = (
        Decimal(portfolio.initial_nav)
        * benchmark_close
        / Decimal(portfolio.benchmark_start_close)
    )
    nav = Decimal(portfolio.nav)
    portfolio.peak_nav = max(Decimal(portfolio.peak_nav), nav)
    drawdown = nav / Decimal(portfolio.peak_nav) - ONE
    portfolio.max_drawdown = max(Decimal(portfolio.max_drawdown), -drawdown)
    current = next(
        (
            snapshot
            for snapshot in snapshots
            if snapshot.contract_code == portfolio.current_contract
        ),
        None,
    )
    position_notional = (
        Decimal(portfolio.quantity)
        * Decimal(portfolio.multiplier)
        * Decimal(current.futures_close)
        if current is not None
        else ZERO
    )
    daily_pnl = nav - prior_nav
    daily_return = daily_pnl / prior_nav if prior_nav else ZERO
    session.add(
        IndexFuturesPaperNav(
            trade_date=trade_date,
            product=portfolio.product,
            contract_code=portfolio.current_contract,
            nav=nav,
            daily_pnl=daily_pnl,
            daily_return=daily_return,
            benchmark_close=benchmark_close,
            benchmark_nav=benchmark_nav,
            position_notional=position_notional,
            cumulative_cost=portfolio.cumulative_cost,
            drawdown=drawdown,
        )
    )


def process_paper_strategy(
    session: Session,
    *,
    config: PaperStrategyConfig,
    products: Iterable[str] = ("IF", "IH", "IC", "IM"),
    up_to: date | None = None,
) -> PaperStrategyUpdateResult:
    result = PaperStrategyUpdateResult()
    if not config.enabled:
        return result
    for product in products:
        if product not in PRODUCT_SPECS:
            continue
        portfolio = _portfolio(session, product, config)
        query = (
            session.query(IndexFuturesBasisSnapshot.trade_date)
            .filter_by(product=product)
            .distinct()
            .order_by(IndexFuturesBasisSnapshot.trade_date)
        )
        if portfolio.last_processed_date is not None:
            query = query.filter(
                IndexFuturesBasisSnapshot.trade_date > portfolio.last_processed_date
            )
        if up_to is not None:
            query = query.filter(IndexFuturesBasisSnapshot.trade_date <= up_to)
        trade_dates = [row[0] for row in query.all()]

        for trade_date in trade_dates:
            if (
                session.query(IndexFuturesPaperNav)
                .filter_by(product=product, trade_date=trade_date)
                .one_or_none()
                is not None
            ):
                portfolio.last_processed_date = trade_date
                continue
            snapshots = (
                session.query(IndexFuturesBasisSnapshot)
                .filter_by(product=product, trade_date=trade_date)
                .order_by(IndexFuturesBasisSnapshot.expiry_date)
                .all()
            )
            if not snapshots:
                continue
            prior_nav = Decimal(portfolio.nav)
            rows_by_code = {snapshot.contract_code: snapshot for snapshot in snapshots}
            _, executed = _execute_pending(
                session,
                portfolio,
                rows_by_code,
                trade_date,
                config,
                result.warnings,
            )
            if executed:
                result.trades += 1
            else:
                _mark_existing_position(
                    session,
                    portfolio,
                    rows_by_code,
                    trade_date,
                    result.warnings,
                )

            # Do not replace a delayed signal. Otherwise, today's close may create the next
            # signal, which can only execute on a strictly later trade date.
            if portfolio.pending_contract is None:
                signal = select_roll_signal(
                    snapshots,
                    current_contract=portfolio.current_contract,
                    minimum_days_to_expiry=config.minimum_days_to_expiry,
                    transaction_cost_bps=Decimal(str(config.transaction_cost_bps)),
                    switch_threshold_annualized=Decimal(
                        str(config.switch_threshold_annualized)
                    ),
                )
                if signal is not None:
                    portfolio.pending_contract = signal.contract_code
                    portfolio.pending_signal_date = trade_date
                    portfolio.pending_reason = signal.reason
                    portfolio.pending_score = signal.net_annualized_score

            _record_nav(session, portfolio, snapshots, trade_date, prior_nav)
            portfolio.last_processed_date = trade_date
            result.processed_dates.add(trade_date)
            session.flush()
    result.warnings = list(dict.fromkeys(result.warnings))
    return result
