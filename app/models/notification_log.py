from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationLog(Base):
    __tablename__ = "notification_log"
    __table_args__ = (
        UniqueConstraint("event_id", "outlet_id", name="uq_notification_log_event_outlet"),
    )

    notification_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("normalized_event.event_id"))
    instrument_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("instrument.instrument_id"), nullable=True
    )
    outlet_id: Mapped[str] = mapped_column(String(100), default="none", index=True)
    channel: Mapped[str] = mapped_column(String(20))
    priority: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="skipped")
    skip_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
