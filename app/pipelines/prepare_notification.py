from sqlalchemy.orm import Session

from app.models.normalized_event import NormalizedEvent
from app.models.notification_log import NotificationLog
from app.models.watchlist import WatchlistItem
from app.rules.priority_rules import determine_notification_priority


def prepare_notifications(session: Session) -> list[NotificationLog]:
    watchlist_ids = {
        item.instrument_id for item in session.query(WatchlistItem).all()
    }

    existing_event_ids = {n.event_id for n in session.query(NotificationLog).all()}

    events = (
        session.query(NormalizedEvent)
        .filter_by(is_duplicate=False)
        .all()
    )

    notifications = []
    for event in events:
        if event.event_id in existing_event_ids:
            continue

        priority = determine_notification_priority(event, watchlist_ids)
        dedupe_key = f"{event.event_type}:{event.primary_instrument_id}:{event.event_time}"

        notif = NotificationLog(
            event_id=event.event_id,
            instrument_id=event.primary_instrument_id,
            channel="webhook",
            priority=priority,
            title=event.title,
            body=event.summary,
            status="skipped",
            skip_reason="notification_channel_not_configured",
            dedupe_key=dedupe_key,
        )
        session.add(notif)
        notifications.append(notif)

    session.flush()
    return notifications
