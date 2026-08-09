from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.digests.config import PaperStrategyConfig
from app.index_futures.paper import (
    net_annualized_score,
    process_paper_strategy,
    select_roll_signal,
)
from app.models.index_futures import (
    IndexFuturesBasisSnapshot,
    IndexFuturesPaperNav,
    IndexFuturesPaperPortfolio,
    IndexFuturesPaperTrade,
)


def _snapshot(
    trade_date: date,
    contract: str,
    *,
    open_: str,
    close: str,
    spot: str = "100",
    dte: int = 30,
    discount_rate: str = "0.02",
    annualized: str = "0.10",
    volume: int = 100,
    open_interest: int = 200,
) -> IndexFuturesBasisSnapshot:
    return IndexFuturesBasisSnapshot(
        trade_date=trade_date,
        product="IF",
        contract_code=contract,
        index_code="000300",
        futures_open=Decimal(open_),
        futures_close=Decimal(close),
        settlement=Decimal(close),
        spot_close=Decimal(spot),
        expiry_date=date(2026, 12, 31),
        days_to_expiry=dte,
        volume=volume,
        open_interest=open_interest,
        discount_points=Decimal(spot) - Decimal(close),
        discount_rate=Decimal(discount_rate),
        annualized_discount_rate=Decimal(annualized),
    )


def test_net_score_eligibility_hysteresis_and_forced_roll():
    current = _snapshot(
        date(2026, 8, 7),
        "IF2608",
        open_="99",
        close="99",
        dte=14,
        discount_rate="0.004",
        annualized="0.10",
    )
    candidate = _snapshot(
        date(2026, 8, 7),
        "IF2609",
        open_="98",
        close="98",
        dte=42,
        discount_rate="0.0143",
        annualized="0.124",
    )
    illiquid = _snapshot(
        date(2026, 8, 7),
        "IF2612",
        open_="90",
        close="90",
        dte=120,
        discount_rate="0.10",
        annualized="0.30",
        volume=0,
    )

    score = net_annualized_score(candidate, Decimal("5"))
    assert score == (Decimal("0.0143") - Decimal("0.0005")) * 365 / 42
    assert (
        select_roll_signal(
            [current, candidate, illiquid],
            current_contract="IF2608",
            minimum_days_to_expiry=10,
            transaction_cost_bps=Decimal("5"),
            switch_threshold_annualized=Decimal("0.02"),
        )
        is None
    )

    current.days_to_expiry = 9
    forced = select_roll_signal(
        [current, candidate, illiquid],
        current_contract="IF2608",
        minimum_days_to_expiry=10,
        transaction_cost_bps=Decimal("5"),
        switch_threshold_annualized=Decimal("0.02"),
    )
    assert forced is not None
    assert forced.contract_code == "IF2609"
    assert forced.reason == "forced_expiry_roll"


def test_strategy_signals_at_close_and_executes_next_open_without_future_data(session):
    first_day = date(2026, 8, 6)
    second_day = date(2026, 8, 7)
    session.add_all(
        [
            _snapshot(
                first_day,
                "IF2608",
                open_="100",
                close="100",
                dte=9,
                discount_rate="0.02",
                annualized="0.80",
            ),
            _snapshot(
                first_day,
                "IF2609",
                open_="98",
                close="98",
                dte=42,
                discount_rate="0.03",
                annualized="0.25",
            ),
            _snapshot(
                second_day,
                "IF2609",
                open_="90",
                close="99",
                dte=41,
                discount_rate="0.03",
                annualized="0.26",
            ),
        ]
    )
    session.flush()
    config = PaperStrategyConfig()

    first = process_paper_strategy(
        session,
        config=config,
        products=["IF"],
        up_to=first_day,
    )
    portfolio = session.get(IndexFuturesPaperPortfolio, "IF")
    assert first.trades == 0
    assert portfolio.current_contract is None
    assert portfolio.pending_contract == "IF2609"
    assert portfolio.pending_signal_date == first_day
    assert Decimal(portfolio.nav) == Decimal("1000000")

    second = process_paper_strategy(
        session,
        config=config,
        products=["IF"],
        up_to=second_day,
    )
    trade = session.query(IndexFuturesPaperTrade).one()
    portfolio = session.get(IndexFuturesPaperPortfolio, "IF")
    expected_cost = Decimal("1000000") * Decimal("0.0005")
    expected_quantity = (Decimal("1000000") - expected_cost) / (Decimal("90") * 300)
    expected_nav = Decimal("1000000") - expected_cost + expected_quantity * 300 * 9

    assert second.trades == 1
    assert trade.signal_date == first_day
    assert trade.execution_date == second_day
    assert Decimal(trade.to_price) == Decimal("90")
    assert Decimal(trade.transaction_cost) == expected_cost
    assert Decimal(portfolio.quantity).quantize(Decimal("0.00000001")) == (
        expected_quantity.quantize(Decimal("0.00000001"))
    )
    assert Decimal(portfolio.nav).quantize(Decimal("0.01")) == expected_nav.quantize(
        Decimal("0.01")
    )
    assert session.query(IndexFuturesPaperNav).count() == 2

    again = process_paper_strategy(session, config=config, products=["IF"])
    assert again.processed_dates == set()
    assert session.query(IndexFuturesPaperTrade).count() == 1


def test_missing_target_open_delays_pending_roll(session):
    first_day = date(2026, 8, 6)
    second_day = date(2026, 8, 7)
    session.add(
        _snapshot(
            first_day,
            "IF2609",
            open_="98",
            close="98",
            dte=42,
            discount_rate="0.03",
            annualized="0.25",
        )
    )
    # Only a different contract appears on the next day, so the target has no opening price.
    session.add(
        _snapshot(
            second_day,
            "IF2612",
            open_="95",
            close="95",
            dte=120,
            discount_rate="0.04",
            annualized="0.12",
        )
    )
    session.flush()

    result = process_paper_strategy(
        session,
        config=PaperStrategyConfig(),
        products=["IF"],
    )
    portfolio = session.get(IndexFuturesPaperPortfolio, "IF")

    assert result.trades == 0
    assert portfolio.current_contract is None
    assert portfolio.pending_contract == "IF2609"
    assert session.query(IndexFuturesPaperTrade).count() == 0
    assert "模拟换月延后" in " ".join(result.warnings)


def test_missing_held_contract_stops_nav_instead_of_writing_unvalued_history(session):
    first_day = date(2026, 8, 5)
    second_day = date(2026, 8, 6)
    third_day = date(2026, 8, 7)
    session.add_all(
        [
            _snapshot(
                first_day,
                "IF2609",
                open_="98",
                close="98",
                dte=42,
                discount_rate="0.03",
                annualized="0.25",
            ),
            _snapshot(
                second_day,
                "IF2609",
                open_="99",
                close="99",
                dte=41,
                discount_rate="0.02",
                annualized="0.18",
            ),
            _snapshot(
                third_day,
                "IF2612",
                open_="95",
                close="95",
                dte=120,
                discount_rate="0.04",
                annualized="0.12",
            ),
        ]
    )
    session.flush()

    result = process_paper_strategy(
        session,
        config=PaperStrategyConfig(),
        products=["IF"],
    )
    portfolio = session.get(IndexFuturesPaperPortfolio, "IF")

    assert portfolio.last_processed_date == second_day
    assert session.query(IndexFuturesPaperNav).count() == 2
    assert "停止推进" in " ".join(result.warnings)


def test_expired_contract_uses_last_settlement_before_next_open_roll(session):
    first_day = date(2026, 2, 13)
    expiry_day = date(2026, 2, 24)
    next_day = date(2026, 2, 25)
    near_first = _snapshot(
        first_day,
        "IF2602",
        open_="98",
        close="98",
        dte=11,
        discount_rate="0.03",
        annualized="0.99",
    )
    near_expiry = _snapshot(
        expiry_day,
        "IF2602",
        open_="99",
        close="100",
        dte=0,
        discount_rate="0",
        annualized="0",
    )
    near_expiry.settlement = Decimal("101")
    far_expiry = _snapshot(
        expiry_day,
        "IF2603",
        open_="97",
        close="97",
        dte=24,
        discount_rate="0.02",
        annualized="0.30",
    )
    far_next = _snapshot(
        next_day,
        "IF2603",
        open_="96",
        close="97",
        dte=23,
        discount_rate="0.02",
        annualized="0.31",
    )
    session.add_all([near_first, near_expiry, far_expiry, far_next])
    session.flush()

    result = process_paper_strategy(
        session,
        config=PaperStrategyConfig(),
        products=["IF"],
    )
    trades = (
        session.query(IndexFuturesPaperTrade)
        .order_by(IndexFuturesPaperTrade.execution_date)
        .all()
    )
    portfolio = session.get(IndexFuturesPaperPortfolio, "IF")

    assert result.trades == 2
    assert trades[-1].from_contract == "IF2602"
    assert Decimal(trades[-1].from_price) == Decimal("101")
    assert trades[-1].to_contract == "IF2603"
    assert Decimal(trades[-1].to_price) == Decimal("96")
    assert portfolio.last_processed_date == next_day
