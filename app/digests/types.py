from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape


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


@dataclass(frozen=True)
class DigestSelectedItem:
    event_id: str
    rank: int
    priority: str
    title: str
    summary: str


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


@dataclass(frozen=True)
class DigestMessagePayload:
    title: str
    body: str | None
    window_start: datetime
    window_end: datetime
    summary: str
    items: list[DigestSelectedItem]

    @property
    def message_body(self) -> str:
        content = self.body.strip() if self.body else "No digest content."
        return f"{self.title}\n\n{content}"

    @property
    def weixin_body(self) -> str:
        if not self.items:
            return self.summary.strip()
        lines = [self.title.strip(), ""]
        for item in self.items:
            lines.append(f"{item.rank}. {item.summary.strip()}")
        return "\n".join(lines).strip()

    @property
    def html_body(self) -> str:
        window = f"{_format_iso_minute(self.window_start)} - {_format_iso_minute(self.window_end)}"
        item_html = "\n".join(
            (
                "<tr>"
                f"<td class=\"rank\">{item.rank}</td>"
                f"<td><span class=\"priority\">{escape(item.priority.upper())}</span></td>"
                f"<td><div class=\"item-title\">{escape(item.title)}</div>"
                f"<div class=\"item-summary\">{escape(item.summary)}</div></td>"
                "</tr>"
            )
            for item in self.items
        )
        if not item_html:
            item_html = (
                "<tr><td colspan=\"3\" class=\"empty\">未发现重要事项。</td></tr>"
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
    .summary {{ padding: 22px 28px; border-bottom: 1px solid #e5e7eb; font-size: 15px; line-height: 1.7; }}
    table {{ width: 100%; border-collapse: collapse; }}
    td {{ padding: 16px 18px; border-bottom: 1px solid #eef0f3; vertical-align: top; }}
    tr:last-child td {{ border-bottom: 0; }}
    .rank {{ width: 36px; color: #6b7280; font-weight: 700; text-align: center; }}
    .priority {{ display: inline-block; min-width: 32px; padding: 3px 8px; border-radius: 999px; background: #eef2ff; color: #3730a3; font-size: 12px; font-weight: 700; text-align: center; }}
    .item-title {{ margin-bottom: 8px; font-size: 16px; line-height: 1.45; font-weight: 700; color: #111827; }}
    .item-summary {{ font-size: 14px; line-height: 1.7; color: #374151; }}
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
      <div class="summary">{escape(self.summary)}</div>
      <table>
        {item_html}
      </table>
    </div>
  </div>
</body>
</html>"""
