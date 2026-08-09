from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from app.digests.config import MarketCommentaryConfig, PaperStrategyConfig
from app.index_futures.commentary import (
    get_or_create_market_commentary,
    validate_market_commentary_output,
)
from app.index_futures.metrics import build_market_metrics
from app.models.index_futures import IndexFuturesBasisSnapshot, IndexFuturesMarketCommentary


def _snapshot(trade_date: date, product: str, code: str, rate: str):
    index_codes = {"IF": "000300", "IH": "000016", "IC": "000905", "IM": "000852"}
    return IndexFuturesBasisSnapshot(
        trade_date=trade_date,
        product=product,
        contract_code=code,
        index_code=index_codes[product],
        futures_open=Decimal("99"),
        futures_close=Decimal("99"),
        settlement=Decimal("99"),
        spot_close=Decimal("100"),
        expiry_date=date(2026, 9, 18),
        days_to_expiry=42,
        volume=100,
        open_interest=200,
        discount_points=Decimal("1"),
        discount_rate=Decimal(rate),
        annualized_discount_rate=Decimal(rate) * 365 / 42,
    )


class _Client:
    model = "test-model"

    def __init__(self, response: dict):
        self.response = response
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        return json.dumps(self.response, ensure_ascii=False)


def _valid_response():
    return {
        "overall_summary": "期限结构保持稳定，贴水仅反映期现关系。",
        "product_commentaries": {
            product: f"{product} 期限结构点评。" for product in ("IF", "IH", "IC", "IM")
        },
        "portfolio_observation": "模拟组合暂无待执行换月。",
        "risk_flags": ["未估计股息、现金利息、保证金收益、真实佣金和滑点。"],
    }


def test_market_metrics_percentiles_and_llm_commentary_cache(session):
    trade_dates = [date(2026, 8, day) for day in range(3, 8)]
    for product in ("IF", "IH", "IC", "IM"):
        for index, trade_date in enumerate(trade_dates):
            session.add(
                _snapshot(
                    trade_date,
                    product,
                    f"{product}2609",
                    str(Decimal("0.01") + Decimal(index) / 1000),
                )
            )
    session.flush()
    metrics = build_market_metrics(
        session,
        trade_date=trade_dates[-1],
        config=PaperStrategyConfig(),
    )
    client = _Client(_valid_response())

    first = get_or_create_market_commentary(
        session,
        metrics=metrics,
        config=MarketCommentaryConfig(),
        client=client,
    )
    second = get_or_create_market_commentary(
        session,
        metrics=metrics,
        config=MarketCommentaryConfig(),
        client=client,
    )

    assert first.used_llm is True
    assert second == first
    assert client.calls == 1
    assert session.query(IndexFuturesMarketCommentary).count() == 1
    assert metrics.products[0].percentiles[0].sample_size == 5
    assert metrics.products[0].percentiles[0].percentile == Decimal("1")


def test_instructional_llm_output_is_rejected_and_falls_back(session):
    trade_date = date(2026, 8, 7)
    for product in ("IF", "IH", "IC", "IM"):
        session.add(_snapshot(trade_date, product, f"{product}2609", "0.01"))
    session.flush()
    metrics = build_market_metrics(
        session,
        trade_date=trade_date,
        config=PaperStrategyConfig(),
    )
    response = _valid_response()
    response["portfolio_observation"] = "建议买入 IF 并加仓。"
    client = _Client(response)

    result = get_or_create_market_commentary(
        session,
        metrics=metrics,
        config=MarketCommentaryConfig(llm={"max_retries": 0}),
        client=client,
    )

    assert result.used_llm is False
    assert result.error == "market_commentary_contains_trading_instruction"
    assert "真实券商佣金" in " ".join(result.risk_flags)


def test_market_commentary_schema_requires_exact_four_products():
    response = _valid_response()
    del response["product_commentaries"]["IM"]
    with pytest.raises(ValueError, match="products_invalid"):
        validate_market_commentary_output(json.dumps(response, ensure_ascii=False))
