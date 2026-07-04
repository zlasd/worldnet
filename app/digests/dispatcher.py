from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.digests.types import DigestDispatchPayload, DigestMessagePayload
from app.models.digest import DigestItem, DigestLog
from app.notifications.base import Notifier
from app.notifications.factory import build_notifiers


class DigestDispatcher:
    def __init__(self, notifiers: list[Notifier]):
        self.notifiers = notifiers

    def dispatch(
        self,
        session: Session,
        payload: DigestDispatchPayload,
        *,
        send: bool = True,
        skip_reason: str | None = None,
    ) -> list[DigestLog]:
        existing_outlet_ids = {
            digest.outlet_id
            for digest in session.query(DigestLog)
            .filter_by(
                digest_type=payload.digest_type,
                window_start=payload.window_start,
                window_end=payload.window_end,
            )
            .all()
        }

        if not self.notifiers:
            if "none" in existing_outlet_ids:
                return []
            digest = self._build_digest_log(
                payload=payload,
                outlet_id="none",
                channel="none",
                status="skipped",
                last_error=skip_reason or "notification_channel_not_configured",
                sent_at=None,
                attempted=False,
            )
            session.add(digest)
            session.flush()
            return [digest]

        digests: list[DigestLog] = []
        for notifier in self.notifiers:
            if notifier.outlet_id in existing_outlet_ids:
                continue

            if not send:
                digest = self._build_digest_log(
                    payload=payload,
                    outlet_id=notifier.outlet_id,
                    channel=notifier.channel,
                    status="skipped",
                    last_error=skip_reason,
                    sent_at=None,
                    attempted=False,
                )
            else:
                result = notifier.send(DigestMessagePayload(title=payload.title, body=payload.body))
                now = datetime.now(timezone.utc)
                digest = self._build_digest_log(
                    payload=payload,
                    outlet_id=notifier.outlet_id,
                    channel=notifier.channel,
                    status="sent" if result.ok else "failed",
                    last_error=payload.last_error if result.ok else result.error,
                    sent_at=now if result.ok else None,
                    attempted=True,
                )
            session.add(digest)
            session.flush()
            self._add_digest_items(session, digest.digest_id, payload)
            digests.append(digest)

        session.flush()
        return digests

    def _build_digest_log(
        self,
        *,
        payload: DigestDispatchPayload,
        outlet_id: str,
        channel: str,
        status: str,
        last_error: str | None,
        sent_at: datetime | None,
        attempted: bool,
    ) -> DigestLog:
        now = datetime.now(timezone.utc)
        return DigestLog(
            digest_type=payload.digest_type,
            window_start=payload.window_start,
            window_end=payload.window_end,
            outlet_id=outlet_id,
            channel=channel,
            title=payload.title,
            body=payload.body,
            status=status,
            attempt_count=1 if attempted else 0,
            last_attempt_at=now if attempted else None,
            last_error=last_error,
            sent_at=sent_at,
            finalized_at=now if status in {"sent", "skipped"} else None,
        )

    def _add_digest_items(
        self,
        session: Session,
        digest_id: str,
        payload: DigestDispatchPayload,
    ) -> None:
        for item in payload.items:
            session.add(
                DigestItem(
                    digest_id=digest_id,
                    event_id=item.event_id,
                    rank=item.rank,
                    priority=item.priority,
                )
            )


def build_digest_dispatcher() -> DigestDispatcher:
    return DigestDispatcher(build_notifiers())
