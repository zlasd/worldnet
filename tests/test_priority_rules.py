from unittest.mock import MagicMock

from app.core.enums import Actionability, NotificationPriority, Severity, SourceTier
from app.rules.priority_rules import (
    determine_actionability,
    determine_notification_priority,
    determine_severity,
)


def test_critical_event_type():
    severity = determine_severity("trading_halt", SourceTier.OFFICIAL)
    assert severity == Severity.CRITICAL


def test_high_severity_official():
    severity = determine_severity("investigation", SourceTier.OFFICIAL)
    assert severity == Severity.CRITICAL


def test_high_severity_non_official():
    severity = determine_severity("buyback", SourceTier.SECONDARY_MEDIA)
    assert severity == Severity.MEDIUM


def test_low_severity_non_official():
    severity = determine_severity("product_launch", SourceTier.SECONDARY_MEDIA)
    assert severity == Severity.LOW


def test_actionability_immediate():
    actionability = determine_actionability(Severity.CRITICAL, SourceTier.OFFICIAL)
    assert actionability == Actionability.IMMEDIATE


def test_actionability_monitor():
    actionability = determine_actionability(Severity.MEDIUM, SourceTier.SECONDARY_MEDIA)
    assert actionability == Actionability.MONITOR


def test_actionability_digest():
    actionability = determine_actionability(Severity.LOW, SourceTier.SECONDARY_MEDIA)
    assert actionability == Actionability.DIGEST_ONLY


def _make_event(severity, source_tier, actionability, primary_instrument_id=None):
    event = MagicMock()
    event.severity = severity
    event.source_tier = source_tier
    event.actionability = actionability
    event.primary_instrument_id = primary_instrument_id
    return event


def test_p1_priority():
    event = _make_event(Severity.CRITICAL, SourceTier.OFFICIAL, Actionability.IMMEDIATE, "instrument-123")
    priority = determine_notification_priority(event, {"instrument-123"})
    assert priority == NotificationPriority.P1


def test_p2_priority_medium():
    event = _make_event(Severity.MEDIUM, SourceTier.SECONDARY_MEDIA, Actionability.MONITOR, "instrument-456")
    priority = determine_notification_priority(event, set())
    assert priority == NotificationPriority.P2


def test_p3_priority_low():
    event = _make_event(Severity.LOW, SourceTier.SECONDARY_MEDIA, Actionability.DIGEST_ONLY, "instrument-789")
    priority = determine_notification_priority(event, set())
    assert priority == NotificationPriority.P3


def test_p1_requires_watchlist():
    event = _make_event(Severity.CRITICAL, SourceTier.OFFICIAL, Actionability.IMMEDIATE, "instrument-123")
    # instrument not in watchlist -> should not be P1
    priority = determine_notification_priority(event, {"other-instrument"})
    assert priority != NotificationPriority.P1
