from __future__ import annotations

import os
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont

from app.digests.types import item_provenance
from app.index_futures.constants import PRODUCT_SPECS, RESEARCH_DISCLAIMER

if TYPE_CHECKING:
    from app.digests.types import DigestMessagePayload
    from app.index_futures.metrics import CurvePoint, MarketMetrics, PortfolioMetric

IMAGE_WIDTH = 1242
IMAGE_MARGIN = 54
IMAGE_BACKGROUND = "#f4f6f8"
CARD_BACKGROUND = "#ffffff"
TEXT_PRIMARY = "#172033"
TEXT_SECONDARY = "#64748b"
ACCENT = "#b45309"
BORDER = "#dbe2ea"
HEADER_BACKGROUND = "#172033"
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
)


def _font_path() -> str:
    configured = os.getenv("DIGEST_IMAGE_FONT_PATH", "").strip()
    for candidate in (configured, *FONT_CANDIDATES):
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("digest_image_chinese_font_not_found")


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_font_path(), size=size)


def _percent(value) -> str:
    return "--" if value is None else f"{float(value) * 100:.2f}%"


def _number(value) -> str:
    return "--" if value is None else f"{float(value):,.2f}"


def _wrap_text(text: str, *, width: int) -> list[str]:
    normalized = " ".join(str(text).split())
    if not normalized:
        return [""]
    return textwrap.wrap(
        normalized,
        width=width,
        break_long_words=True,
        break_on_hyphens=False,
        replace_whitespace=False,
    ) or [normalized]


def _text_height(lines: list[str], font: ImageFont.FreeTypeFont, spacing: int = 8) -> int:
    line_height = font.size + 8
    return len(lines) * line_height + max(0, len(lines) - 1) * spacing


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    lines: list[str],
    *,
    font: ImageFont.FreeTypeFont,
    fill: str = TEXT_PRIMARY,
    spacing: int = 8,
) -> int:
    x, y = xy
    line_height = font.size + 8
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height + spacing
    return y - spacing


def _maturity_label(point: CurvePoint) -> str:
    return point.expiry_date.strftime("%Y-%m")


def _metrics_rows(metrics: MarketMetrics) -> tuple[list[str], dict[tuple[str, str], CurvePoint]]:
    months = sorted({_maturity_label(point) for point in metrics.curves})
    curves = {(point.product, _maturity_label(point)): point for point in metrics.curves}
    return months, curves


def _portfolio_line(portfolio: PortfolioMetric) -> str:
    return (
        f"{portfolio.product}  当前 {portfolio.current_contract or '未建仓'}  "
        f"待执行 {portfolio.pending_contract or '无'}  NAV {_number(portfolio.nav)}  "
        f"收益 {_percent(portfolio.cumulative_return)}  回撤 {_percent(portfolio.max_drawdown)}"
    )


def _pe_line(metric) -> str:
    if metric is None or metric.current_pe is None:
        return "PE --｜历史PE分位 --"
    percentile = _percent(metric.pe_percentile)
    return (
        f"PE {_number(metric.current_pe)}｜"
        f"历史PE分位（{metric.pe_percentile_lookback}日） {percentile}"
    )


def _build_blocks(payload: DigestMessagePayload) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    blocks.append(("summary", _wrap_text(payload.summary, width=43)))
    if payload.items:
        for item in payload.items:
            title = f"{item.rank}. [{item.priority.upper()}] {item.title}"
            blocks.append(("news-title", _wrap_text(title, width=39)))
            blocks.append(("news-summary", _wrap_text(item.summary, width=43)))
            for line in item_provenance(item):
                blocks.append(("news-source", _wrap_text(line, width=60)))
    else:
        blocks.append(("news-summary", ["未发现重要事项。"]))

    section = payload.market_section
    if section is None:
        return blocks
    if section.metrics is None:
        blocks.extend(
            [
                ("section", ["二、股指期货贴水监控"]),
                ("market-note", ["暂无可用的同日官方行情。"]),
            ]
        )
        return blocks

    metrics = section.metrics
    months, curves = _metrics_rows(metrics)
    product_metrics = {metric.product: metric for metric in metrics.products}
    blocks.append(("section", ["二、股指期货贴水监控"]))
    blocks.append(("market-note", [f"交易日 {metrics.trade_date.isoformat()}｜正数贴水，负数升水"]))
    blocks.append(("subsection", ["期货贴水率"]))
    for product in PRODUCT_SPECS:
        product_points = [point for point in metrics.curves if point.product == product]
        if not product_points:
            continue
        blocks.append(
            (
                "product",
                [
                    f"{product} {PRODUCT_SPECS[product].index_name}｜现货 {_number(product_points[0].spot_close)}"
                ],
            )
        )
        blocks.append(("market-note", [_pe_line(product_metrics.get(product))]))
        for month in months:
            point = curves.get((product, month))
            if point is None:
                continue
            blocks.append(
                (
                    "contract",
                    [
                        f"{month}  {point.contract_code}  {_number(point.futures_close)}  "
                        f"到期 {point.expiry_date.strftime('%m-%d')}（{point.days_to_expiry}天）  "
                        f"贴水 {_percent(point.discount_rate)}  "
                        f"年化贴水 {_percent(point.annualized_discount_rate)}"
                    ],
                )
            )

    blocks.append(("subsection", ["模拟持仓"]))
    for portfolio in metrics.portfolios:
        blocks.append(("portfolio", _wrap_text(_portfolio_line(portfolio), width=48)))
    blocks.append(("disclaimer", [RESEARCH_DISCLAIMER]))
    commentary = (
        " ".join(section.commentary.overall_summary.split())[:300]
        if section.commentary is not None
        else "当日简评不可用。"
    )
    blocks.append(("commentary", _wrap_text(f"简评：{commentary}", width=43)))
    return blocks


def _block_style(kind: str) -> tuple[ImageFont.FreeTypeFont, str, int, int]:
    if kind == "news-source":
        return _font(20), TEXT_SECONDARY, 3, 4
    if kind == "section":
        return _font(34), TEXT_PRIMARY, 30, 12
    if kind == "subsection":
        return _font(28), TEXT_PRIMARY, 24, 8
    if kind in {"news-title", "product"}:
        return _font(28), TEXT_PRIMARY, 18, 5
    if kind == "contract":
        return _font(23), ACCENT, 5, 5
    if kind == "disclaimer":
        return _font(21), ACCENT, 16, 5
    if kind == "commentary":
        return _font(26), TEXT_PRIMARY, 16, 8
    if kind == "summary":
        return _font(27), TEXT_SECONDARY, 0, 10
    return _font(24), TEXT_SECONDARY, 5, 7


def render_digest_jpeg(payload: DigestMessagePayload, output_path: str | Path) -> Path:
    """Render a deterministic, single-image Weixin digest."""
    blocks = _build_blocks(payload)
    header_height = 154
    card_padding = 38
    # Reserve the standalone news heading drawn before the generated blocks.
    content_height = card_padding + 52
    for kind, lines in blocks:
        font, _, before, spacing = _block_style(kind)
        content_height += before + _text_height(lines, font, spacing)
    content_height += card_padding
    height = header_height + IMAGE_MARGIN + content_height + IMAGE_MARGIN

    image = Image.new("RGB", (IMAGE_WIDTH, height), IMAGE_BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, IMAGE_WIDTH, header_height), fill=HEADER_BACKGROUND)
    draw.text((IMAGE_MARGIN, 34), payload.title, font=_font(42), fill="#ffffff")
    window = f"{payload.window_start:%Y-%m-%d %H:%M} — {payload.window_end:%Y-%m-%d %H:%M}"
    draw.text((IMAGE_MARGIN, 98), window, font=_font(22), fill="#cbd5e1")

    left = IMAGE_MARGIN
    top = header_height + 26
    right = IMAGE_WIDTH - IMAGE_MARGIN
    bottom = top + content_height
    draw.rounded_rectangle((left, top, right, bottom), radius=18, fill=CARD_BACKGROUND)
    x = left + card_padding
    y = top + card_padding
    draw.text((x, y), "一、重要新闻", font=_font(34), fill=TEXT_PRIMARY)
    y += 52
    for kind, lines in blocks:
        font, fill, before, spacing = _block_style(kind)
        y += before
        if kind in {"section", "subsection"}:
            draw.line((x, y - 8, right - card_padding, y - 8), fill=BORDER, width=2)
        indent = 22 if kind == "contract" else 0
        y = _draw_lines(draw, (x + indent, y), lines, font=font, fill=fill, spacing=spacing)

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="JPEG", quality=88, optimize=True, progressive=True)
    return destination
