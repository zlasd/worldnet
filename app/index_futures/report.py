from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from html import escape

from app.index_futures.commentary import MarketCommentary
from app.index_futures.constants import PRODUCT_SPECS, RESEARCH_DISCLAIMER
from app.index_futures.metrics import MarketMetrics


@dataclass(frozen=True)
class IndexFuturesDigestSection:
    metrics: MarketMetrics | None
    commentary: MarketCommentary | None
    warnings: tuple[str, ...] = ()


def _percent(value: Decimal | None, digits: int = 2) -> str:
    return "--" if value is None else f"{float(value) * 100:.{digits}f}%"


def _number(value: Decimal | None, digits: int = 2) -> str:
    return "--" if value is None else f"{float(value):,.{digits}f}"


def render_market_plain(section: IndexFuturesDigestSection) -> str:
    if section.metrics is None:
        lines = ["一、四品种四期限贴水", "暂无可用的同日官方行情。"]
        if section.warnings:
            lines.extend(["", "数据提示：", *[f"- {warning}" for warning in section.warnings]])
        lines.extend(["", RESEARCH_DISCLAIMER])
        return "\n".join(lines)

    metrics = section.metrics
    lines = [
        "一、四品种四期限贴水",
        f"交易日：{metrics.trade_date.isoformat()}（正数为贴水，负数为升水）",
        "品种 合约 剩余天数 期货收盘 现货收盘 贴水点数 贴水率 年化贴水率 成交量 持仓量",
    ]
    for point in metrics.curves:
        lines.append(
            " ".join(
                [
                    point.product,
                    point.contract_code,
                    str(point.days_to_expiry),
                    _number(point.futures_close),
                    _number(point.spot_close),
                    _number(point.discount_points),
                    _percent(point.discount_rate),
                    _percent(point.annualized_discount_rate),
                    str(point.volume),
                    str(point.open_interest),
                ]
            )
        )
    lines.extend(["", "历史分位（每日最优合约净年化得分）："])
    for product in metrics.products:
        percentiles = " / ".join(
            f"{item.lookback}日 {_percent(item.percentile, 1)}(n={item.sample_size})"
            for item in product.percentiles
        )
        lines.append(
            f"- {product.product} 最优净年化 {_percent(product.best_net_annualized_score)}；"
            f"{percentiles}"
        )

    lines.extend(["", "二、模拟组合状态 / 待执行模拟换月", RESEARCH_DISCLAIMER])
    for portfolio in metrics.portfolios:
        pending = (
            f"{portfolio.pending_contract}（信号日 {portfolio.pending_signal_date}，"
            f"原因 {portfolio.pending_reason}）"
            if portfolio.pending_contract
            else "无"
        )
        lines.append(
            f"- {portfolio.product}：当前 {portfolio.current_contract or '未建仓'}；"
            f"待执行 {pending}；NAV {_number(portfolio.nav)}；"
            f"收益 {_percent(portfolio.cumulative_return)}；超额 {_percent(portfolio.excess_return)}；"
            f"最大回撤 {_percent(portfolio.max_drawdown)}；换月 {portfolio.roll_count} 次；"
            f"累计成本 {_number(portfolio.cumulative_cost)}"
        )

    lines.extend(["", "三、LLM 市场点评"])
    commentary = section.commentary
    if commentary is None:
        lines.append("市场点评不可用。")
    else:
        source = "LLM" if commentary.used_llm else "确定性模板降级"
        lines.extend([f"点评来源：{source}", commentary.overall_summary])
        for product in PRODUCT_SPECS:
            lines.append(f"- {product}：{commentary.product_commentaries.get(product, '暂无点评。')}")
        lines.append(f"- 组合观察：{commentary.portfolio_observation}")
        lines.append("- 风险提示：" + "；".join(commentary.risk_flags))
        if commentary.error:
            lines.append(f"- 点评降级原因：{commentary.error}")
    warnings = tuple(dict.fromkeys((*metrics.warnings, *section.warnings)))
    if warnings:
        lines.extend(["", "数据与模型提示：", *[f"- {warning}" for warning in warnings]])
    return "\n".join(lines)


def render_market_html(section: IndexFuturesDigestSection) -> str:
    if section.metrics is None:
        warnings = "".join(f"<li>{escape(item)}</li>" for item in section.warnings)
        return (
            '<section class="market-section"><h2>一、四品种四期限贴水</h2>'
            '<div class="market-empty">暂无可用的同日官方行情。</div>'
            f'<ul class="warnings">{warnings}</ul>'
            f'<div class="disclaimer">{escape(RESEARCH_DISCLAIMER)}</div></section>'
        )

    metrics = section.metrics
    curve_rows = "".join(
        "<tr>"
        f"<td><strong>{escape(point.product)}</strong></td>"
        f"<td>{escape(point.contract_code)}</td>"
        f"<td>{point.days_to_expiry}</td>"
        f"<td>{_number(point.futures_close)}</td>"
        f"<td>{_number(point.spot_close)}</td>"
        f"<td>{_number(point.discount_points)}</td>"
        f"<td>{_percent(point.discount_rate)}</td>"
        f"<td>{_percent(point.annualized_discount_rate)}</td>"
        f"<td>{point.volume:,}</td>"
        f"<td>{point.open_interest:,}</td>"
        "</tr>"
        for point in metrics.curves
    )
    percentile_rows = "".join(
        "<tr>"
        f"<td><strong>{escape(product.product)}</strong></td>"
        f"<td>{_percent(product.best_net_annualized_score)}</td>"
        + "".join(
            f"<td>{_percent(item.percentile, 1)} <span class=\"sample\">n={item.sample_size}</span></td>"
            for item in product.percentiles
        )
        + "</tr>"
        for product in metrics.products
    )
    portfolio_rows = "".join(
        "<tr>"
        f"<td><strong>{escape(portfolio.product)}</strong></td>"
        f"<td>{escape(portfolio.current_contract or '未建仓')}</td>"
        f"<td>{escape(portfolio.pending_contract or '无')}</td>"
        f"<td>{_number(portfolio.nav)}</td>"
        f"<td>{_percent(portfolio.cumulative_return)}</td>"
        f"<td>{_percent(portfolio.excess_return)}</td>"
        f"<td>{_percent(portfolio.max_drawdown)}</td>"
        f"<td>{portfolio.roll_count}</td>"
        f"<td>{_number(portfolio.cumulative_cost)}</td>"
        "</tr>"
        for portfolio in metrics.portfolios
    )
    commentary = section.commentary
    if commentary is None:
        commentary_html = '<div class="market-empty">市场点评不可用。</div>'
    else:
        products_html = "".join(
            f"<li><strong>{product}</strong> {escape(commentary.product_commentaries.get(product, '暂无点评。'))}</li>"
            for product in PRODUCT_SPECS
        )
        risks_html = "".join(f"<li>{escape(risk)}</li>" for risk in commentary.risk_flags)
        source = "LLM" if commentary.used_llm else "确定性模板降级"
        commentary_html = (
            f'<div class="commentary-source">点评来源：{escape(source)}</div>'
            f'<p>{escape(commentary.overall_summary)}</p><ul>{products_html}</ul>'
            f'<p><strong>组合观察：</strong>{escape(commentary.portfolio_observation)}</p>'
            f'<div class="risk-title">风险提示</div><ul class="warnings">{risks_html}</ul>'
        )
    warnings = tuple(dict.fromkeys((*metrics.warnings, *section.warnings)))
    warnings_html = "".join(f"<li>{escape(item)}</li>" for item in warnings)
    return f"""
<section class="market-section">
  <h2>一、四品种四期限贴水</h2>
  <div class="market-date">交易日：{metrics.trade_date.isoformat()}（正数为贴水，负数为升水）</div>
  <div class="table-scroll"><table class="market-table">
    <thead><tr><th>品种</th><th>合约</th><th>剩余天数</th><th>期货收盘</th><th>现货收盘</th><th>贴水点数</th><th>贴水率</th><th>年化</th><th>成交量</th><th>持仓量</th></tr></thead>
    <tbody>{curve_rows}</tbody>
  </table></div>
  <h3>历史分位（每日最优合约净年化得分）</h3>
  <table class="market-table"><thead><tr><th>品种</th><th>当前</th><th>20日</th><th>60日</th><th>252日</th></tr></thead><tbody>{percentile_rows}</tbody></table>
</section>
<section class="market-section">
  <h2>二、模拟组合状态 / 待执行模拟换月</h2>
  <div class="disclaimer">{escape(RESEARCH_DISCLAIMER)}</div>
  <div class="table-scroll"><table class="market-table"><thead><tr><th>品种</th><th>当前</th><th>待执行</th><th>NAV</th><th>收益</th><th>超额</th><th>最大回撤</th><th>换月</th><th>成本</th></tr></thead><tbody>{portfolio_rows}</tbody></table></div>
</section>
<section class="market-section commentary">
  <h2>三、LLM 市场点评</h2>
  {commentary_html}
</section>
<section class="market-section notes">
  <h3>数据与模型提示</h3><ul class="warnings">{warnings_html}</ul>
</section>"""
