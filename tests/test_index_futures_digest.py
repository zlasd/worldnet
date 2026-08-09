from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.digests.dispatcher import DigestDispatcher
from app.digests.runner import run_important_daily_digest
from app.index_futures.official import BasisHistoryResult, BasisValue
from app.models.index_futures import (
    IndexFuturesMarketCommentary,
    IndexFuturesPaperNav,
    IndexFuturesPaperPortfolio,
)
from app.notifications.base import NotificationResult


class _Notifier:
    outlet_id = "fixture"
    channel = "email"

    def __init__(self):
        self.payloads = []

    def send(self, payload):
        self.payloads.append(payload)
        return NotificationResult(ok=True)


class _OfficialClient:
    def __init__(self):
        self.calls = 0

    def fetch_basis_history(self, **kwargs):
        self.calls += 1
        values = []
        index_codes = {"IF": "000300", "IH": "000016", "IC": "000905", "IM": "000852"}
        for product in index_codes:
            for rank, month in enumerate((8, 9, 12, 3), start=1):
                year = 2027 if month == 3 else 2026
                contract = f"{product}{str(year)[-2:]}{month:02d}"
                close = Decimal("100") - Decimal(rank)
                rate = (Decimal("100") - close) / Decimal("100")
                values.append(
                    BasisValue(
                        trade_date=date(2026, 8, 7),
                        product=product,
                        contract_code=contract,
                        index_code=index_codes[product],
                        futures_open=close,
                        futures_close=close,
                        settlement=close,
                        spot_close=Decimal("100"),
                        expiry_date=date(year, month, 21 if month != 3 else 19),
                        days_to_expiry=14 + rank * 30,
                        volume=1000 * rank,
                        open_interest=2000 * rank,
                        discount_points=Decimal("100") - close,
                        discount_rate=rate,
                        annualized_discount_rate=rate * 365 / (14 + rank * 30),
                    )
                )
        return BasisHistoryResult(values=values, warnings=[])


class _CommentaryClient:
    model = "fixture-model"

    def __init__(self):
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        return json.dumps(
            {
                "overall_summary": "四品种期限结构数据完整，贴水不代表方向。",
                "product_commentaries": {
                    product: f"{product} 期限结构点评。"
                    for product in ("IF", "IH", "IC", "IM")
                },
                "portfolio_observation": "模拟组合已形成下一交易日待执行信号。",
                "risk_flags": [
                    "未估计股息、现金利息、保证金收益、真实佣金和滑点。"
                ],
            },
            ensure_ascii=False,
        )


def _config():
    return {
        "llm": {"enabled": False},
        "market_sections": {
            "index_futures_basis": {
                "enabled": True,
                "products": ["IF", "IH", "IC", "IM"],
                "history_days": 252,
            }
        },
        "paper_strategy": {"enabled": True},
        "market_commentary": {"enabled": True, "llm": {"enabled": True, "max_retries": 0}},
    }


def test_daily_digest_includes_market_before_news_and_sends_without_news(session):
    notifier = _Notifier()
    official = _OfficialClient()
    commentary = _CommentaryClient()
    now = datetime(2026, 8, 10, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    result = run_important_daily_digest(
        session,
        _config(),
        now=now,
        dispatcher=DigestDispatcher([notifier]),
        market_data_client=official,
        market_llm_client=commentary,
    )

    assert result["digests"] == 1
    assert result["market_trade_date"] == "2026-08-07"
    assert result["paper_trades"] == 0
    assert result["market_used_llm"] is True
    assert official.calls == commentary.calls == 1
    assert session.query(IndexFuturesPaperPortfolio).count() == 4
    assert session.query(IndexFuturesPaperNav).count() == 4
    payload = notifier.payloads[0]
    assert payload.body.index("一、四品种四期限贴水") < payload.body.index("四、重要新闻")
    assert "模拟研究，不连接真实账户，不构成交易指令" in payload.message_body
    assert "IF2608" in payload.weixin_body
    assert "<h2>一、四品种四期限贴水</h2>" in payload.html_body
    assert "<h2>四、重要新闻</h2>" in payload.html_body


def test_same_trade_date_reuses_commentary_and_does_not_advance_nav(session):
    official = _OfficialClient()
    commentary = _CommentaryClient()
    first_notifier = _Notifier()
    first_now = datetime(2026, 8, 8, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    second_now = datetime(2026, 8, 9, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    run_important_daily_digest(
        session,
        _config(),
        now=first_now,
        dispatcher=DigestDispatcher([first_notifier]),
        market_data_client=official,
        market_llm_client=commentary,
    )
    second_notifier = _Notifier()
    result = run_important_daily_digest(
        session,
        _config(),
        now=second_now,
        dispatcher=DigestDispatcher([second_notifier]),
        market_data_client=official,
        market_llm_client=commentary,
    )

    assert result["digests"] == 1
    assert commentary.calls == 1
    assert session.query(IndexFuturesMarketCommentary).count() == 1
    assert session.query(IndexFuturesPaperNav).count() == 4
    assert len(second_notifier.payloads) == 1
