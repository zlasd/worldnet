from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NormalizedEvent(Base):
    __tablename__ = "normalized_event"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("source_document.document_id"))
    event_type: Mapped[str] = mapped_column(String(50))
    event_subtype: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    market: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    primary_instrument_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("instrument.instrument_id"), nullable=True
    )
    related_instrument_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    event_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(20), default="low")
    sentiment: Mapped[str] = mapped_column(String(20), default="neutral")
    novelty_score: Mapped[float] = mapped_column(Float, default=0.5)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.5)
    actionability: Mapped[str] = mapped_column(String(20), default="digest_only")
    source_tier: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_event_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    schema_version: Mapped[str] = mapped_column(String(20), default="1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
