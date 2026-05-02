from __future__ import annotations

from app.core.enums import Actionability, NotificationPriority, Severity, SourceTier

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
    "investigation",
}


def determine_severity(event_type: str, source_tier: str) -> Severity:
    if event_type in CRITICAL_EVENT_TYPES:
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
    if severity == Severity.MEDIUM:
        return Actionability.MONITOR
    return Actionability.DIGEST_ONLY


def determine_notification_priority(event: "NormalizedEvent", watchlist_instrument_ids: set[str]) -> NotificationPriority:  # type: ignore[name-defined]  # noqa: F821
    if (
        event.source_tier == SourceTier.OFFICIAL
        and event.severity in (Severity.CRITICAL, Severity.HIGH)
        and event.actionability == Actionability.IMMEDIATE
        and event.primary_instrument_id in watchlist_instrument_ids
    ):
        return NotificationPriority.P1

    if event.severity == Severity.MEDIUM or event.actionability == Actionability.MONITOR:
        return NotificationPriority.P2

    return NotificationPriority.P3
