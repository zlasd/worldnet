from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.notification_log import NotificationLog
from app.notifications.base import NotificationPayload, Notifier
from app.notifications.factory import build_notifiers


class NotificationDispatcher:
    def __init__(self, notifiers: list[Notifier]):
        self.notifiers = notifiers

    def dispatch(self, session: Session, payload: NotificationPayload) -> list[NotificationLog]:
        existing_outlet_ids = {
            notification.outlet_id
            for notification in session.query(NotificationLog).filter_by(event_id=payload.event_id).all()
        }

        if not self.notifiers:
            if "none" in existing_outlet_ids:
                return []
            notification = self._build_log(
                payload=payload,
                outlet_id="none",
                channel="none",
                status="skipped",
                skip_reason="notification_channel_not_configured",
                sent_at=None,
            )
            session.add(notification)
            session.flush()
            return [notification]

        notifications: list[NotificationLog] = []
        for notifier in self.notifiers:
            if notifier.outlet_id in existing_outlet_ids:
                continue

            result = notifier.send(payload)
            if result.ok:
                notification = self._build_log(
                    payload=payload,
                    outlet_id=notifier.outlet_id,
                    channel=notifier.channel,
                    status="sent",
                    skip_reason=None,
                    sent_at=datetime.now(timezone.utc),
                )
            else:
                notification = self._build_log(
                    payload=payload,
                    outlet_id=notifier.outlet_id,
                    channel=notifier.channel,
                    status="failed",
                    skip_reason=result.error,
                    sent_at=None,
                )
            session.add(notification)
            notifications.append(notification)

        session.flush()
        return notifications

    def _build_log(
        self,
        *,
        payload: NotificationPayload,
        outlet_id: str,
        channel: str,
        status: str,
        skip_reason: str | None,
        sent_at: datetime | None,
    ) -> NotificationLog:
        return NotificationLog(
            event_id=payload.event_id,
            instrument_id=payload.instrument_id,
            outlet_id=outlet_id,
            channel=channel,
            priority=payload.priority,
            title=payload.title,
            body=payload.body,
            status=status,
            skip_reason=skip_reason,
            dedupe_key=payload.dedupe_key,
            sent_at=sent_at,
        )


def build_notification_dispatcher() -> NotificationDispatcher:
    return NotificationDispatcher(build_notifiers())
