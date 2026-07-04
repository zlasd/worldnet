from datetime import datetime, timezone

from app.models.normalized_event import NormalizedEvent
from app.pipelines.prepare_notification import prepare_notifications
from app.services.qq_agent_mail_service import MailSendResult, parse_recipients


def _add_event(session):
    event = NormalizedEvent(
        event_id="event-1",
        document_id="document-1",
        title="Policy update",
        summary="A policy update was published.",
        event_type="policy_change",
        severity="medium",
        sentiment="neutral",
        actionability="monitor",
        event_time=datetime.now(timezone.utc),
        is_duplicate=False,
    )
    session.add(event)
    session.flush()
    return event


def test_parse_recipients_accepts_commas_and_semicolons():
    assert parse_recipients("a@example.com, b@example.com;c@example.com") == [
        "a@example.com",
        "b@example.com",
        "c@example.com",
    ]


def test_prepare_notifications_skips_when_mail_disabled(session, monkeypatch):
    monkeypatch.setattr("app.pipelines.prepare_notification.settings.qq_agent_mail_enabled", False)
    _add_event(session)

    notifications = prepare_notifications(session)

    assert len(notifications) == 1
    assert notifications[0].channel == "webhook"
    assert notifications[0].status == "skipped"
    assert notifications[0].skip_reason == "notification_channel_not_configured"


def test_prepare_notifications_sends_qq_agent_mail(session, monkeypatch):
    sent = {}

    def fake_send_qq_agent_mail(*, recipients, subject, body):
        sent["recipients"] = recipients
        sent["subject"] = subject
        sent["body"] = body
        return MailSendResult(ok=True)

    monkeypatch.setattr("app.pipelines.prepare_notification.settings.qq_agent_mail_enabled", True)
    monkeypatch.setattr(
        "app.pipelines.prepare_notification.settings.qq_agent_mail_to",
        "desk@example.com",
    )
    monkeypatch.setattr(
        "app.pipelines.prepare_notification.send_qq_agent_mail",
        fake_send_qq_agent_mail,
    )
    _add_event(session)

    notifications = prepare_notifications(session)

    assert len(notifications) == 1
    assert notifications[0].channel == "email"
    assert notifications[0].status == "sent"
    assert notifications[0].skip_reason is None
    assert notifications[0].sent_at is not None
    assert sent == {
        "recipients": ["desk@example.com"],
        "subject": "Policy update",
        "body": "Policy update\n\nA policy update was published.",
    }


def test_prepare_notifications_records_qq_agent_mail_failure(session, monkeypatch):
    monkeypatch.setattr("app.pipelines.prepare_notification.settings.qq_agent_mail_enabled", True)
    monkeypatch.setattr(
        "app.pipelines.prepare_notification.settings.qq_agent_mail_to",
        "desk@example.com",
    )
    monkeypatch.setattr(
        "app.pipelines.prepare_notification.send_qq_agent_mail",
        lambda **_: MailSendResult(ok=False, error="agently_cli_not_found"),
    )
    _add_event(session)

    notifications = prepare_notifications(session)

    assert len(notifications) == 1
    assert notifications[0].channel == "email"
    assert notifications[0].status == "failed"
    assert notifications[0].skip_reason == "agently_cli_not_found"
