from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DigestLog(Base):
    __tablename__ = "digest_log"
    __table_args__ = (
        UniqueConstraint(
            "digest_type",
            "window_start",
            "window_end",
            "outlet_id",
            name="uq_digest_log_window_outlet",
        ),
    )

    digest_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    digest_type: Mapped[str] = mapped_column(String(50))
    window_start: Mapped[datetime] = mapped_column(DateTime)
    window_end: Mapped[datetime] = mapped_column(DateTime)
    outlet_id: Mapped[str] = mapped_column(String(100), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DigestItem(Base):
    __tablename__ = "digest_item"
    __table_args__ = (
        UniqueConstraint("digest_id", "event_id", name="uq_digest_item_digest_event"),
    )

    digest_item_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    digest_id: Mapped[str] = mapped_column(String(36), ForeignKey("digest_log.digest_id"))
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("normalized_event.event_id"))
    rank: Mapped[int] = mapped_column(Integer)
    priority: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
