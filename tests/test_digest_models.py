from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.digest import DigestItem, DigestLog
from app.models.normalized_event import NormalizedEvent


def _add_event(session, event_id: str) -> NormalizedEvent:
    event = NormalizedEvent(
        event_id=event_id,
        document_id=f"document-{event_id}",
        title=f"Event {event_id}",
        summary="Digest candidate.",
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


def _add_digest(
    session,
    *,
    digest_id: str = "digest-1",
    outlet_id: str = "qq_agent_mail",
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> DigestLog:
    start = window_start or datetime(2026, 7, 4, tzinfo=timezone.utc)
    end = window_end or start + timedelta(days=1)
    digest = DigestLog(
        digest_id=digest_id,
        digest_type="important_daily",
        window_start=start,
        window_end=end,
        outlet_id=outlet_id,
        channel="email",
        title="Daily important events",
        body="Summary body",
    )
    session.add(digest)
    session.flush()
    return digest


def test_digest_log_can_be_created(session):
    digest = _add_digest(session)

    assert digest.status == "pending"
    assert digest.attempt_count == 0
    assert digest.created_at is not None
    assert digest.updated_at is not None


def test_digest_can_reference_multiple_events(session):
    digest = _add_digest(session)
    _add_event(session, "event-1")
    _add_event(session, "event-2")

    session.add_all(
        [
            DigestItem(
                digest_item_id="digest-item-1",
                digest_id=digest.digest_id,
                event_id="event-1",
                rank=1,
                priority="p1",
            ),
            DigestItem(
                digest_item_id="digest-item-2",
                digest_id=digest.digest_id,
                event_id="event-2",
                rank=2,
                priority="p2",
            ),
        ]
    )
    session.flush()

    items = session.query(DigestItem).filter_by(digest_id=digest.digest_id).all()
    assert {item.event_id for item in items} == {"event-1", "event-2"}


def test_digest_item_rejects_duplicate_event_in_same_digest(session):
    digest = _add_digest(session)
    _add_event(session, "event-1")
    session.add(
        DigestItem(
            digest_item_id="digest-item-1",
            digest_id=digest.digest_id,
            event_id="event-1",
            rank=1,
            priority="p1",
        )
    )
    session.flush()

    session.add(
        DigestItem(
            digest_item_id="digest-item-2",
            digest_id=digest.digest_id,
            event_id="event-1",
            rank=2,
            priority="p1",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_digest_log_rejects_duplicate_window_for_same_outlet(session):
    start = datetime(2026, 7, 4, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    _add_digest(session, digest_id="digest-1", outlet_id="qq_agent_mail", window_start=start, window_end=end)

    with pytest.raises(IntegrityError):
        _add_digest(
            session,
            digest_id="digest-2",
            outlet_id="qq_agent_mail",
            window_start=start,
            window_end=end,
        )


def test_digest_log_allows_same_window_for_different_outlets(session):
    start = datetime(2026, 7, 4, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    _add_digest(session, digest_id="digest-1", outlet_id="qq_agent_mail", window_start=start, window_end=end)
    _add_digest(session, digest_id="digest-2", outlet_id="hermes_weixin", window_start=start, window_end=end)

    assert session.query(DigestLog).count() == 2
