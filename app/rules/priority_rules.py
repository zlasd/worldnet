from __future__ import annotations

import re

from app.core.enums import Actionability, NotificationPriority, Severity, SourceTier
from app.rules.text_rules import contains_term, management_change_kind

HIGH_SEVERITY_EVENT_TYPES = {
    "earnings_preannouncement",
    "profit_warning",
    "guidance_change",
    "buyback",
    "major_holder_change",
    "management_change",
    "mna",
    "investigation",
    "litigation",
    "audit_issue",
    "trading_halt",
    "delisting_risk",
}

CRITICAL_EVENT_TYPES = {
    "trading_halt",
    "delisting_risk",
}


def determine_severity(
    event_type: str, source_tier: str, title: str = "", raw_text: str = ""
) -> Severity:
    if event_type == "management_change":
        if management_change_kind(title, raw_text) == "departure":
            return Severity.HIGH
        return Severity.MEDIUM
    if event_type in CRITICAL_EVENT_TYPES:
        if title:
            terms = (
                ("trading halt", "trading suspended", "trading suspension", "suspends trading", "halt trading", "停牌", "暂停买卖")
                if event_type == "trading_halt" else ("delisting", "delist", "退市")
            )
            if not any(contains_term(title, term) for term in terms):
                # A passing reference in a roundup is not a fresh risk alert.
                return Severity.MEDIUM
            if event_type == "trading_halt" and (
                "临时停牌" in title
                or re.search(r"ETF|LOF|可转债|转债", title, re.IGNORECASE)
            ):
                return Severity.MEDIUM
        return Severity.CRITICAL
    if event_type in HIGH_SEVERITY_EVENT_TYPES:
        if source_tier == SourceTier.OFFICIAL:
            return Severity.HIGH
        return Severity.MEDIUM
    if source_tier == SourceTier.OFFICIAL:
        return Severity.MEDIUM
    return Severity.LOW


def determine_actionability(severity: str, source_tier: str) -> Actionability:
    if severity in (Severity.CRITICAL, Severity.HIGH) and source_tier == SourceTier.OFFICIAL:
        return Actionability.IMMEDIATE
    if severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM):
        return Actionability.MONITOR
    return Actionability.DIGEST_ONLY


def determine_notification_priority(event: "NormalizedEvent", watchlist_instrument_ids: set[str]) -> NotificationPriority:  # type: ignore[name-defined]  # noqa: F821
    if event.event_type in {"macro_release_reminder", "macro_data_release", "central_bank_decision"} and event.source_tier == SourceTier.OFFICIAL:
        return NotificationPriority.P1
    # Importance is attention priority, not permission to trade. Credibility
    # and watchlist relevance are separate fields, not prerequisites for P1.
    if event.severity in (Severity.CRITICAL, Severity.HIGH):
        return NotificationPriority.P1

    if event.severity == Severity.MEDIUM or event.actionability == Actionability.MONITOR:
        return NotificationPriority.P2

    return NotificationPriority.P3


def priority_reason(event: "NormalizedEvent") -> str:  # type: ignore[name-defined]  # noqa: F821
    if event.event_type in {"macro_release_reminder", "macro_data_release", "central_bank_decision"} and event.source_tier == SourceTier.OFFICIAL:
        return "官方宏观发布/日程"
    if event.severity == Severity.CRITICAL:
        return "重大交易/退市风险"
    if event.severity == Severity.HIGH:
        if event.event_type == "management_change":
            return "关键管理层离任"
        return "高影响公司事件"
    if event.severity == Severity.MEDIUM or event.actionability == Actionability.MONITOR:
        return "需跟踪的实质变化"
    return "常规资讯/背景信息"
