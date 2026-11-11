from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.digests.config import MarketCommentaryConfig
from app.digests.llm import DigestLlmClient, OpenAICompatibleDigestClient
from app.index_futures.constants import PRODUCT_SPECS
from app.index_futures.metrics import MarketMetrics
from app.models.index_futures import IndexFuturesMarketCommentary

PROMPT_VERSION = "v3"
MAX_SUMMARY_LENGTH = 300
FORBIDDEN_ACTION_PHRASES = (
    "买入",
    "卖出",
    "加仓",
    "减仓",
    "开仓",
    "平仓",
    "做多",
    "做空",
)
REQUIRED_RISK_TERMS = ("股息", "现金利息", "保证金收益", "佣金", "滑点")
OUTPUT_KEYS = {
    "overall_summary",
    "product_commentaries",
    "portfolio_observation",
    "risk_flags",
}


@dataclass(frozen=True)
class MarketCommentary:
    overall_summary: str
    product_commentaries: dict[str, str]
    portfolio_observation: str
    risk_flags: tuple[str, ...]
    used_llm: bool
    error: str | None = None


def build_market_commentary_messages(metrics: MarketMetrics) -> list[dict[str, str]]:
    system_prompt = (
        "你是股指期货期限结构研究日报的事实点评器。只返回 JSON，不使用 Markdown。"
        "必须返回 overall_summary 字符串、product_commentaries 对象、"
        "portfolio_observation 字符串、risk_flags 字符串数组。"
        "product_commentaries 必须且只能包含 IF、IH、IC、IM 四个键。"
        "overall_summary 是日报唯一展示的简评，必须为单段中文且不超过 300 个字符，"
        "浓缩概括四个品种的贴水期限结构和模拟持仓；其他字段仅用于内部审计。"
        "只解释输入中的贴水、期限结构、PE估值、流动性和模拟组合，不推测未提供的数据。"
        "不得出现买入、卖出、加仓、减仓、开仓、平仓、做多、做空等真实交易动作。"
        "贴水不是方向指标。所有组合均为模拟研究，不连接真实账户。"
        "风险提示必须覆盖：未估计预期股息、现金利息、保证金收益、真实佣金和滑点。"
    )
    user_prompt = (
        "请根据以下结构化摘要生成简洁中文市场点评：\n"
        + json.dumps(metrics.prompt_payload(), ensure_ascii=False, sort_keys=True)
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def validate_market_commentary_output(content: str) -> MarketCommentary:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("market_commentary_invalid_json") from exc
    if not isinstance(payload, dict):
        raise ValueError("market_commentary_not_object")
    if set(payload) != OUTPUT_KEYS:
        raise ValueError("market_commentary_fields_invalid")
    overall = payload.get("overall_summary")
    products = payload.get("product_commentaries")
    portfolio = payload.get("portfolio_observation")
    risks = payload.get("risk_flags")
    if not isinstance(overall, str) or not overall.strip():
        raise ValueError("market_commentary_summary_empty")
    if "\n" in overall or "\r" in overall:
        raise ValueError("market_commentary_summary_not_single_paragraph")
    if len(overall.strip()) > MAX_SUMMARY_LENGTH:
        raise ValueError("market_commentary_summary_too_long")
    if not isinstance(products, dict) or set(products) != set(PRODUCT_SPECS):
        raise ValueError("market_commentary_products_invalid")
    if any(not isinstance(value, str) or not value.strip() for value in products.values()):
        raise ValueError("market_commentary_product_empty")
    if not isinstance(portfolio, str) or not portfolio.strip():
        raise ValueError("market_commentary_portfolio_empty")
    if not isinstance(risks, list) or not risks or any(
        not isinstance(value, str) or not value.strip() for value in risks
    ):
        raise ValueError("market_commentary_risks_invalid")
    combined = " ".join(
        [overall, *products.values(), portfolio, *risks]
    )
    if any(phrase in combined for phrase in FORBIDDEN_ACTION_PHRASES):
        raise ValueError("market_commentary_contains_trading_instruction")
    risk_text = " ".join(risks)
    if any(term not in risk_text for term in REQUIRED_RISK_TERMS):
        raise ValueError("market_commentary_missing_required_risk")
    return MarketCommentary(
        overall_summary=overall.strip(),
        product_commentaries={key: str(products[key]).strip() for key in PRODUCT_SPECS},
        portfolio_observation=portfolio.strip(),
        risk_flags=tuple(str(value).strip() for value in risks),
        used_llm=True,
    )


def _fallback(metrics: MarketMetrics, error: str | None) -> MarketCommentary:
    product_comments: dict[str, str] = {}
    metric_by_product = {metric.product: metric for metric in metrics.products}
    for product in PRODUCT_SPECS:
        metric = metric_by_product.get(product)
        if metric is None or metric.best_net_annualized_score is None:
            product_comments[product] = "当日有效期限结构或流动性样本不足。"
            continue
        percentile_252 = next(
            (item for item in metric.percentiles if item.lookback == 252),
            None,
        )
        percentile_text = (
            f"，252日分位 {float(percentile_252.percentile) * 100:.1f}%"
            if percentile_252 is not None and percentile_252.percentile is not None
            else "，252日分位样本不足"
        )
        product_comments[product] = (
            f"当前最优合约净年化得分 {float(metric.best_net_annualized_score) * 100:.2f}%"
            f"{percentile_text}；该数值仅描述期限结构。"
        )
    pending = [
        f"{portfolio.product}->{portfolio.pending_contract}"
        for portfolio in metrics.portfolios
        if portfolio.pending_contract
    ]
    return MarketCommentary(
        overall_summary=(
            f"截至 {metrics.trade_date.isoformat()}，期限结构与模拟组合已按确定性规则更新；"
            "贴水不直接代表市场方向。"
        ),
        product_commentaries=product_comments,
        portfolio_observation=(
            "待下一交易日开盘执行的模拟换月：" + "、".join(pending)
            if pending
            else "当前没有待下一交易日执行的模拟换月。"
        ),
        risk_flags=(
            "未估计预期股息、现金利息和保证金收益。",
            "未计入真实券商佣金与滑点，5bp 仅为模拟综合成本。",
            "贴水同时受股息、利率、资金成本和套利力量影响，不是方向指标。",
            *metrics.warnings,
        ),
        used_llm=False,
        error=error,
    )


def _from_record(record: IndexFuturesMarketCommentary) -> MarketCommentary:
    return MarketCommentary(
        overall_summary=record.overall_summary,
        product_commentaries=json.loads(record.product_commentaries),
        portfolio_observation=record.portfolio_observation,
        risk_flags=tuple(json.loads(record.risk_flags)),
        used_llm=record.used_llm,
        error=record.error,
    )


def get_or_create_market_commentary(
    session: Session,
    *,
    metrics: MarketMetrics,
    config: MarketCommentaryConfig,
    client: DigestLlmClient | None = None,
) -> MarketCommentary:
    llm_client = client or OpenAICompatibleDigestClient()
    cache_model = (
        getattr(llm_client, "model", None)
        if config.enabled and config.llm.enabled
        else None
    )
    cached = (
        session.query(IndexFuturesMarketCommentary)
        .filter_by(trade_date=metrics.trade_date)
        .one_or_none()
    )
    if (
        cached is not None
        and cached.prompt_version == PROMPT_VERSION
        and cached.model == cache_model
        and (cached.used_llm or not (config.enabled and config.llm.enabled))
    ):
        return _from_record(cached)

    payload = metrics.prompt_payload()
    input_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    input_hash = hashlib.sha256(input_json.encode()).hexdigest()
    commentary: MarketCommentary | None = None
    last_error: str | None = None
    if config.enabled and config.llm.enabled:
        for _ in range(config.llm.max_retries + 1):
            try:
                commentary = validate_market_commentary_output(
                    llm_client.complete(build_market_commentary_messages(metrics))
                )
                break
            except Exception as exc:
                last_error = str(exc) or exc.__class__.__name__
    else:
        last_error = "market_commentary_llm_disabled"
    if commentary is None:
        commentary = _fallback(metrics, last_error)

    record = cached or IndexFuturesMarketCommentary(trade_date=metrics.trade_date)
    record.input_hash = input_hash
    record.prompt_version = PROMPT_VERSION
    record.model = cache_model
    record.overall_summary = commentary.overall_summary
    record.product_commentaries = json.dumps(
        commentary.product_commentaries,
        ensure_ascii=False,
        sort_keys=True,
    )
    record.portfolio_observation = commentary.portfolio_observation
    record.risk_flags = json.dumps(commentary.risk_flags, ensure_ascii=False)
    record.used_llm = commentary.used_llm
    record.error = commentary.error
    if cached is None:
        session.add(record)
    session.flush()
    return commentary
