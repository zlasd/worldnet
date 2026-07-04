from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.digests.config import parse_digest_task_config
from app.digests.dispatcher import DigestDispatcher
from app.digests.runner import determine_digest_window, run_important_daily_digest
from app.models.digest import DigestItem, DigestLog
from app.models.normalized_event import NormalizedEvent
from app.notifications.base import NotificationResult


class FakeNotifier:
    outlet_id = "qq_agent_mail"
    channel = "email"

    def __init__(self):
        self.sent_payloads = []

    def send(self, payload):
        self.sent_payloads.append(payload)
        return NotificationResult(ok=True)


def _add_event(
    session,
    *,
    event_id: str = "event-1",
    detected_at: datetime,
    severity: str = "medium",
    actionability: str = "monitor",
    is_duplicate: bool = False,
) -> None:
    session.add(
        NormalizedEvent(
            event_id=event_id,
            document_id=f"document-{event_id}",
            title=f"Event {event_id}",
            summary="Important event summary.",
            event_type="policy_change",
            severity=severity,
            sentiment="neutral",
            actionability=actionability,
            detected_at=detected_at,
            event_time=detected_at,
            is_duplicate=is_duplicate,
        )
    )
    session.flush()


def test_determine_digest_window_uses_previous_day_on_first_run(session):
    now = datetime(2026, 7, 5, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    window_start, window_end = determine_digest_window(
        session,
        "important_daily",
        now,
        config=parse_digest_task_config({}),
    )

    assert window_start == datetime(2026, 7, 3, 16, 0)
    assert window_end == datetime(2026, 7, 4, 23, 30)


def test_determine_digest_window_uses_last_window_end(session):
    previous_end = datetime(2026, 7, 4, 23, 30)
    session.add(
        DigestLog(
            digest_type="important_daily",
            window_start=previous_end - timedelta(days=1),
            window_end=previous_end,
            outlet_id="qq_agent_mail",
            channel="email",
            title="Digest",
            body="Body",
            status="sent",
        )
    )
    session.flush()

    window_start, window_end = determine_digest_window(
        session,
        "important_daily",
        datetime(2026, 7, 6, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        config=parse_digest_task_config({}),
    )

    assert window_start == previous_end
    assert window_end == datetime(2026, 7, 5, 23, 30)


def test_run_important_daily_digest_sends_and_records_items(session):
    notifier = FakeNotifier()
    dispatcher = DigestDispatcher([notifier])
    _add_event(session, detected_at=datetime(2026, 7, 4, 10, 0))

    result = run_important_daily_digest(
        session,
        {
            "llm": {"enabled": False},
            "selection": {"max_items": 5},
        },
        now=datetime(2026, 7, 5, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        dispatcher=dispatcher,
    )

    digest = session.query(DigestLog).one()
    assert result["items"] == 1
    assert result["digests"] == 1
    assert digest.status == "sent"
    assert digest.sent_at is not None
    assert session.query(DigestItem).filter_by(digest_id=digest.digest_id).count() == 1
    assert len(notifier.sent_payloads) == 1
    assert "Event event-1" in notifier.sent_payloads[0].message_body


def test_run_important_daily_digest_skips_empty_digest_without_sending(session):
    notifier = FakeNotifier()
    dispatcher = DigestDispatcher([notifier])

    result = run_important_daily_digest(
        session,
        {"llm": {"enabled": False}, "rendering": {"include_empty_digest": False}},
        now=datetime(2026, 7, 5, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        dispatcher=dispatcher,
    )

    digest = session.query(DigestLog).one()
    assert result["items"] == 0
    assert digest.status == "skipped"
    assert digest.last_error == "no_digest_items"
    assert notifier.sent_payloads == []


def test_run_important_daily_digest_ignores_duplicate_events(session):
    notifier = FakeNotifier()
    dispatcher = DigestDispatcher([notifier])
    _add_event(session, event_id="duplicate", detected_at=datetime(2026, 7, 4, 10, 0), is_duplicate=True)

    result = run_important_daily_digest(
        session,
        {"llm": {"enabled": False}},
        now=datetime(2026, 7, 5, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        dispatcher=dispatcher,
    )

    assert result["candidates"] == 0
    assert result["items"] == 0
    assert notifier.sent_payloads == []


def test_run_important_daily_digest_does_not_repeat_empty_window(session):
    notifier = FakeNotifier()
    dispatcher = DigestDispatcher([notifier])
    _add_event(session, detected_at=datetime(2026, 7, 4, 10, 0))
    now = datetime(2026, 7, 5, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    first = run_important_daily_digest(
        session,
        {"llm": {"enabled": False}},
        now=now,
        dispatcher=dispatcher,
    )
    second = run_important_daily_digest(
        session,
        {"llm": {"enabled": False}},
        now=now,
        dispatcher=dispatcher,
    )

    assert first["digests"] == 1
    assert second["digests"] == 0
    assert second["error"] == "empty_digest_window"
