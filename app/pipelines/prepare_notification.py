from sqlalchemy.orm import Session

from app.models.normalized_event import NormalizedEvent
from app.models.notification_log import NotificationLog
from app.models.watchlist import WatchlistItem
from app.notifications.base import NotificationPayload
from app.notifications.dispatcher import NotificationDispatcher, build_notification_dispatcher
from app.rules.priority_rules import determine_notification_priority


def prepare_notifications(
    session: Session,
    dispatcher: NotificationDispatcher | None = None,
) -> list[NotificationLog]:
    dispatcher = dispatcher or build_notification_dispatcher()
    watchlist_ids = {
        item.instrument_id for item in session.query(WatchlistItem).all()
    }

    events = (
        session.query(NormalizedEvent)
        .filter_by(is_duplicate=False)
        .all()
    )

    notifications = []
    for event in events:
        priority = determine_notification_priority(event, watchlist_ids)
        priority_value = getattr(priority, "value", priority)
        dedupe_key = f"{event.event_type}:{event.primary_instrument_id}:{event.event_time}"
        payload = NotificationPayload(
            event_id=event.event_id,
            instrument_id=event.primary_instrument_id,
            priority=priority_value,
            title=event.title,
            body=event.summary,
            dedupe_key=dedupe_key,
        )
        notifications.extend(dispatcher.dispatch(session, payload))

    session.flush()
    return notifications
