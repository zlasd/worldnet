from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.normalized_event import NormalizedEvent
from app.models.notification_log import NotificationLog
from app.models.watchlist import WatchlistItem
from app.rules.priority_rules import determine_notification_priority
from app.services.qq_agent_mail_service import (
    build_notification_email_body,
    parse_recipients,
    send_qq_agent_mail,
)


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

        channel = "email" if settings.qq_agent_mail_enabled else "webhook"
        status = "skipped"
        skip_reason = "notification_channel_not_configured"
        sent_at = None

        if settings.qq_agent_mail_enabled:
            send_result = send_qq_agent_mail(
                recipients=parse_recipients(settings.qq_agent_mail_to),
                subject=event.title,
                body=build_notification_email_body(event.title, event.summary),
            )
            if send_result.ok:
                status = "sent"
                skip_reason = None
                sent_at = datetime.now(timezone.utc)
            else:
                status = "failed"
                skip_reason = send_result.error

        notif = NotificationLog(
            event_id=event.event_id,
            instrument_id=event.primary_instrument_id,
            channel=channel,
            priority=priority,
            title=event.title,
            body=event.summary,
            status=status,
            skip_reason=skip_reason,
            dedupe_key=dedupe_key,
            sent_at=sent_at,
        )
        session.add(notif)
        notifications.append(notif)

    session.flush()
    return notifications
