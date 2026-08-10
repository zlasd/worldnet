from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from html import escape

from app.index_futures.commentary import MarketCommentary
from app.index_futures.constants import PRODUCT_SPECS, RESEARCH_DISCLAIMER
from app.index_futures.metrics import CurvePoint, MarketMetrics


@dataclass(frozen=True)
class IndexFuturesDigestSection:
    metrics: MarketMetrics | None
    commentary: MarketCommentary | None
    warnings: tuple[str, ...] = ()


def _percent(value: Decimal | None, digits: int = 2) -> str:
    return "--" if value is None else f"{float(value) * 100:.{digits}f}%"


def _number(value: Decimal | None, digits: int = 2) -> str:
    return "--" if value is None else f"{float(value):,.{digits}f}"


def _products(metrics: MarketMetrics) -> tuple[str, ...]:
    available = {item.product for item in metrics.products} | {
        point.product for point in metrics.curves
    }
    return tuple(product for product in PRODUCT_SPECS if product in available)


def _maturity_months(metrics: MarketMetrics) -> tuple[str, ...]:
    return tuple(sorted({point.expiry_date.strftime("%Y-%m") for point in metrics.curves}))


def _curve_lookup(metrics: MarketMetrics) -> dict[tuple[str, str], CurvePoint]:
    return {
        (point.product, point.expiry_date.strftime("%Y-%m")): point
        for point in metrics.curves
    }


def _commentary_text(commentary: MarketCommentary | None) -> str:
    if commentary is None:
        return "当日简评不可用。"
    return " ".join(commentary.overall_summary.split())[:300]


def _plain_curve_cell(point: CurvePoint | None) -> str:
    if point is None:
        return "--"
    return (
        f"{point.contract_code} {_number(point.futures_close)}；"
        f"到期 {point.expiry_date.strftime('%m-%d')}（{point.days_to_expiry}天）；"
        f"贴水 {_percent(point.discount_rate)}"
    )


def render_market_plain(section: IndexFuturesDigestSection) -> str:
    lines = ["二、股指期货贴水监控"]
    if section.metrics is None:
        lines.append("暂无可用的同日官方行情。")
        if section.warnings:
            lines.append("数据提示：" + "；".join(dict.fromkeys(section.warnings)))
        return "\n".join(lines)

    metrics = section.metrics
    products = _products(metrics)
    months = _maturity_months(metrics)
    curves = _curve_lookup(metrics)
    lines.extend(
        [
            f"交易日：{metrics.trade_date.isoformat()}（正数为贴水，负数为升水）",
            "",
            "贴水率表",
            " | ".join(("品种 / 现货", *months)),
            " | ".join(("---", *("---" for _ in months))),
        ]
    )
    for product in products:
        spot = next((point.spot_close for point in metrics.curves if point.product == product), None)
        spot_cell = f"{product} {PRODUCT_SPECS[product].index_name} {_number(spot)}"
        lines.append(
            " | ".join(
                (spot_cell, *(_plain_curve_cell(curves.get((product, month))) for month in months))
            )
        )

    lines.extend(
        [
            "",
            "模拟持仓表",
            "品种 | 当前模拟持仓 | 待执行换月 | NAV | 累计收益 | 最大回撤",
            "--- | --- | --- | --- | --- | ---",
        ]
    )
    portfolios = {portfolio.product: portfolio for portfolio in metrics.portfolios}
    for product in products:
        portfolio = portfolios.get(product)
        if portfolio is None:
            lines.append(f"{product} | -- | -- | -- | -- | --")
            continue
        lines.append(
            " | ".join(
                (
                    product,
                    portfolio.current_contract or "未建仓",
                    portfolio.pending_contract or "无",
                    _number(portfolio.nav),
                    _percent(portfolio.cumulative_return),
                    _percent(portfolio.max_drawdown),
                )
            )
        )
    lines.extend(
        [
            RESEARCH_DISCLAIMER,
            f"简评：{_commentary_text(section.commentary)}",
        ]
    )
    return "\n".join(lines)


def _html_curve_cell(point: CurvePoint | None) -> str:
    if point is None:
        return '<span class="muted">--</span>'
    return (
        f'<div class="contract"><strong>{escape(point.contract_code)}</strong> '
        f'{_number(point.futures_close)}</div>'
        f'<div class="cell-detail">到期 {point.expiry_date.strftime("%m-%d")} '
        f'（{point.days_to_expiry}天）</div>'
        f'<div class="basis-rate">贴水 {_percent(point.discount_rate)}</div>'
    )


def render_market_html(section: IndexFuturesDigestSection) -> str:
    if section.metrics is None:
        warning = "；".join(dict.fromkeys(section.warnings))
        warning_html = f'<div class="data-note">数据提示：{escape(warning)}</div>' if warning else ""
        return (
            '<section class="market-section"><h2>二、股指期货贴水监控</h2>'
            '<div class="market-empty">暂无可用的同日官方行情。</div>'
            f"{warning_html}</section>"
        )

    metrics = section.metrics
    products = _products(metrics)
    months = _maturity_months(metrics)
    curves = _curve_lookup(metrics)
    curve_rows: list[str] = []
    for product in products:
        spot = next((point.spot_close for point in metrics.curves if point.product == product), None)
        cells = "".join(
            f"<td>{_html_curve_cell(curves.get((product, month)))}</td>" for month in months
        )
        curve_rows.append(
            "<tr>"
            f'<td><strong>{escape(product)}</strong> {escape(PRODUCT_SPECS[product].index_name)}'
            f'<div class="spot-points">现货 {_number(spot)}</div></td>'
            f"{cells}</tr>"
        )
    month_headers = "".join(f"<th>{escape(month)}</th>" for month in months)

    portfolios = {portfolio.product: portfolio for portfolio in metrics.portfolios}
    portfolio_rows: list[str] = []
    for product in products:
        portfolio = portfolios.get(product)
        if portfolio is None:
            portfolio_rows.append(
                f"<tr><td><strong>{escape(product)}</strong></td>"
                "<td>--</td><td>--</td><td>--</td><td>--</td><td>--</td></tr>"
            )
            continue
        portfolio_rows.append(
            "<tr>"
            f"<td><strong>{escape(product)}</strong></td>"
            f"<td>{escape(portfolio.current_contract or '未建仓')}</td>"
            f"<td>{escape(portfolio.pending_contract or '无')}</td>"
            f"<td>{_number(portfolio.nav)}</td>"
            f"<td>{_percent(portfolio.cumulative_return)}</td>"
            f"<td>{_percent(portfolio.max_drawdown)}</td>"
            "</tr>"
        )

    return f"""
<section class="market-section">
  <h2>二、股指期货贴水监控</h2>
  <div class="market-date">交易日：{metrics.trade_date.isoformat()}（正数为贴水，负数为升水）</div>
  <h3>期货贴水率</h3>
  <div class="table-scroll"><table class="market-table basis-table">
    <thead><tr><th>品种 / 现货</th>{month_headers}</tr></thead>
    <tbody>{''.join(curve_rows)}</tbody>
  </table></div>
  <h3>模拟持仓</h3>
  <div class="table-scroll"><table class="market-table">
    <thead><tr><th>品种</th><th>当前模拟持仓</th><th>待执行换月</th><th>NAV</th><th>累计收益</th><th>最大回撤</th></tr></thead>
    <tbody>{''.join(portfolio_rows)}</tbody>
  </table></div>
  <div class="disclaimer">{escape(RESEARCH_DISCLAIMER)}</div>
  <p class="market-commentary"><strong>简评：</strong>{escape(_commentary_text(section.commentary))}</p>
</section>"""
