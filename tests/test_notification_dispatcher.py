from datetime import datetime, timezone

from app.models.normalized_event import NormalizedEvent
from app.notifications.base import NotificationPayload, NotificationResult
from app.notifications.dispatcher import NotificationDispatcher
from app.pipelines.prepare_notification import prepare_notifications


class FakeNotifier:
    def __init__(self, outlet_id: str, channel: str, result: NotificationResult):
        self.outlet_id = outlet_id
        self.channel = channel
        self.result = result
        self.sent_payloads: list[NotificationPayload] = []

    def send(self, payload: NotificationPayload) -> NotificationResult:
        self.sent_payloads.append(payload)
        return self.result


def _add_event(session, event_id: str = "event-1") -> NormalizedEvent:
    event = NormalizedEvent(
        event_id=event_id,
        document_id=f"document-{event_id}",
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


def test_prepare_notifications_skips_when_no_outlets_are_enabled(session):
    _add_event(session)

    notifications = prepare_notifications(session, dispatcher=NotificationDispatcher([]))

    assert len(notifications) == 1
    assert notifications[0].outlet_id == "none"
    assert notifications[0].channel == "none"
    assert notifications[0].status == "skipped"
    assert notifications[0].skip_reason == "notification_channel_not_configured"
    assert notifications[0].attempt_count == 0
    assert notifications[0].last_error is None
    assert notifications[0].updated_at is not None


def test_prepare_notifications_fans_out_to_multiple_outlets(session):
    mail = FakeNotifier("qq_agent_mail", "email", NotificationResult(ok=True))
    weixin = FakeNotifier("hermes_weixin", "weixin", NotificationResult(ok=True))
    _add_event(session)

    notifications = prepare_notifications(
        session,
        dispatcher=NotificationDispatcher([mail, weixin]),
    )

    assert len(notifications) == 2
    assert {notification.outlet_id for notification in notifications} == {
        "qq_agent_mail",
        "hermes_weixin",
    }
    assert all(notification.status == "sent" for notification in notifications)
    assert all(notification.sent_at is not None for notification in notifications)
    assert len(mail.sent_payloads) == 1
    assert len(weixin.sent_payloads) == 1


def test_prepare_notifications_records_per_outlet_failure(session):
    mail = FakeNotifier("qq_agent_mail", "email", NotificationResult(ok=False, error="failed"))
    _add_event(session)

    notifications = prepare_notifications(session, dispatcher=NotificationDispatcher([mail]))

    assert len(notifications) == 1
    assert notifications[0].outlet_id == "qq_agent_mail"
    assert notifications[0].channel == "email"
    assert notifications[0].status == "failed"
    assert notifications[0].skip_reason == "failed"
    assert notifications[0].sent_at is None


def test_prepare_notifications_does_not_repeat_existing_event_outlet_pair(session):
    mail = FakeNotifier("qq_agent_mail", "email", NotificationResult(ok=True))
    _add_event(session)
    dispatcher = NotificationDispatcher([mail])

    first_run = prepare_notifications(session, dispatcher=dispatcher)
    second_run = prepare_notifications(session, dispatcher=dispatcher)

    assert len(first_run) == 1
    assert second_run == []
    assert len(mail.sent_payloads) == 1


def test_prepare_notifications_allows_new_outlet_for_existing_event(session):
    mail = FakeNotifier("qq_agent_mail", "email", NotificationResult(ok=True))
    weixin = FakeNotifier("hermes_weixin", "weixin", NotificationResult(ok=True))
    _add_event(session)

    prepare_notifications(session, dispatcher=NotificationDispatcher([mail]))
    notifications = prepare_notifications(session, dispatcher=NotificationDispatcher([mail, weixin]))

    assert len(notifications) == 1
    assert notifications[0].outlet_id == "hermes_weixin"
    assert len(mail.sent_payloads) == 1
    assert len(weixin.sent_payloads) == 1
