from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from app.index_futures.report import IndexFuturesDigestSection


def _format_iso_minute(value: datetime) -> str:
    if value.tzinfo is None:
        return f"{value.isoformat(timespec='minutes')}Z"
    return value.isoformat(timespec="minutes")


@dataclass(frozen=True)
class DigestCandidate:
    event_id: str
    title: str
    summary: str | None
    priority: str
    event_type: str
    severity: str
    actionability: str
    source_name: str | None
    source_tier: str | None
    detected_at: datetime
    event_time: datetime | None
    instrument_id: str | None
    source_url: str | None = None
    published_at: datetime | None = None
    selection_reason: str | None = None
    watchlist_match: bool = False


@dataclass(frozen=True)
class DigestSelectedItem:
    event_id: str
    rank: int
    priority: str
    title: str
    summary: str
    source_name: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    selection_reason: str | None = None


def safe_source_url(value: str | None) -> str | None:
    if not value or any(ord(char) < 32 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
        ):
            return value
    except ValueError:
        pass
    return None


def item_provenance(item: DigestSelectedItem) -> list[str]:
    lines = []
    if item.source_name:
        lines.append(f"来源：{item.source_name}")
    if item.published_at:
        lines.append(f"发布：{_format_iso_minute(item.published_at)}")
    if url := safe_source_url(item.source_url):
        lines.append(f"原文：{url}")
    if item.selection_reason:
        lines.append(f"入选依据：{item.selection_reason}")
    return lines


def _provenance_html(item: DigestSelectedItem) -> str:
    parts = []
    for line in item_provenance(item):
        if line.startswith("原文："):
            parts.append(f'<a href="{escape(line[3:], quote=True)}">阅读原文</a>')
        else:
            parts.append(escape(line))
    return '<div class="item-source">' + "<br>".join(parts) + "</div>" if parts else ""


@dataclass(frozen=True)
class DigestSelectionResult:
    summary: str
    items: list[DigestSelectedItem]
    used_llm: bool
    error: str | None = None


@dataclass(frozen=True)
class DigestDispatchPayload:
    digest_type: str
    window_start: datetime
    window_end: datetime
    title: str
    summary: str
    body: str
    items: list[DigestSelectedItem]
    last_error: str | None = None
    market_section: IndexFuturesDigestSection | None = None


@dataclass(frozen=True)
class DigestMessagePayload:
    title: str
    body: str | None
    window_start: datetime
    window_end: datetime
    summary: str
    items: list[DigestSelectedItem]
    market_section: IndexFuturesDigestSection | None = None

    @property
    def message_body(self) -> str:
        content = self.body.strip() if self.body else "No digest content."
        return f"{self.title}\n\n{content}"

    @property
    def weixin_body(self) -> str:
        lines = [self.title.strip(), "", "一、重要新闻", self.summary.strip(), ""]
        if not self.items:
            lines.append("未发现重要事项。")
        else:
            for item in self.items:
                lines.extend(
                    [
                        f"{item.rank}. [{item.priority.upper()}] {item.title.strip()}",
                        f"   {item.summary.strip()}",
                    ]
                )
                lines.extend(f"   {line}" for line in item_provenance(item))
        if self.market_section is not None:
            from app.index_futures.report import render_market_plain

            lines.extend(["", render_market_plain(self.market_section)])
        return "\n".join(lines).strip()

    @property
    def html_body(self) -> str:
        window = f"{_format_iso_minute(self.window_start)} - {_format_iso_minute(self.window_end)}"
        market_html = ""
        if self.market_section is not None:
            from app.index_futures.report import render_market_html

            market_html = render_market_html(self.market_section)
        item_html = "\n".join(
            (
                "<tr>"
                f'<td><div class="item-title">{item.rank}. '
                f"[{escape(item.priority.upper())}] {escape(item.title)}</div>"
                f'<div class="item-summary">{escape(item.summary)}</div>'
                f"{_provenance_html(item)}</td>"
                "</tr>"
            )
            for item in self.items
        )
        if not item_html:
            item_html = '<tr><td class="empty">未发现重要事项。</td></tr>'

        news_heading = "<h2>一、重要新闻</h2>" if self.market_section is not None else ""
        news_html = (
            '<section class="news-section">'
            f"{news_heading}"
            f'<div class="summary">{escape(self.summary)}</div>'
            f"<table>{item_html}</table>"
            "</section>"
        )

        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ margin: 0; padding: 0; background: #f6f7f9; color: #1f2937; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .wrap {{ max-width: 760px; margin: 0 auto; padding: 28px 20px; }}
    .panel {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden; }}
    .header {{ padding: 24px 28px; background: #111827; color: #ffffff; }}
    h1 {{ margin: 0 0 8px; font-size: 22px; line-height: 1.3; }}
    .window {{ font-size: 13px; color: #d1d5db; }}
    .news-section {{ border-bottom: 1px solid #e5e7eb; }}
    .news-section h2 {{ padding: 20px 28px 0; }}
    .summary {{ padding: 18px 28px; border-bottom: 1px solid #e5e7eb; font-size: 15px; line-height: 1.7; }}
    .market-section {{ padding: 20px 28px; border-bottom: 1px solid #e5e7eb; }}
    h2 {{ margin: 0 0 14px; font-size: 18px; color: #111827; }}
    h3 {{ margin: 18px 0 10px; font-size: 15px; color: #1f2937; }}
    .market-date, .commentary-source {{ margin-bottom: 12px; color: #6b7280; font-size: 13px; }}
    .table-scroll {{ overflow-x: auto; }}
    .market-table th {{ padding: 9px 8px; background: #f3f4f6; color: #4b5563; font-size: 12px; text-align: left; white-space: nowrap; }}
    .market-table td {{ padding: 10px 8px; font-size: 12px; text-align: left; white-space: nowrap; }}
    .basis-table td {{ white-space: normal; min-width: 112px; }}
    .basis-table td:first-child {{ min-width: 104px; }}
    .spot-points, .spot-pe, .cell-detail {{ margin-top: 3px; color: #6b7280; }}
    .basis-rate {{ margin-top: 3px; color: #b45309; font-weight: 700; }}
    .muted, .data-note {{ color: #6b7280; }}
    .disclaimer {{ margin: 14px 0 0; color: #92400e; font-size: 12px; }}
    .market-commentary {{ margin: 12px 0 0; font-size: 14px; line-height: 1.7; }}
    .market-empty {{ color: #6b7280; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td {{ padding: 16px 18px; border-bottom: 1px solid #eef0f3; vertical-align: top; }}
    tr:last-child td {{ border-bottom: 0; }}
    .item-title {{ margin-bottom: 8px; font-size: 16px; line-height: 1.45; font-weight: 700; color: #111827; }}
    .item-summary {{ font-size: 14px; line-height: 1.7; color: #374151; }}
    .item-source {{ margin-top: 8px; font-size: 12px; line-height: 1.6; color: #64748b; overflow-wrap: anywhere; }}
    .empty {{ color: #6b7280; text-align: center; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <div class="header">
        <h1>{escape(self.title)}</h1>
        <div class="window">{escape(window)}</div>
      </div>
      {news_html}
      {market_html}
    </div>
  </div>
</body>
</html>"""
