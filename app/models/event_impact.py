from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EventImpact(Base):
    __tablename__ = "event_impact"

    impact_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("normalized_event.event_id"))
    instrument_id: Mapped[str] = mapped_column(String(36), ForeignKey("instrument.instrument_id"))
    direction: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # bullish|bearish|neutral
    impact_horizon: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # short|medium|long
    impact_strength: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    thesis_change: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # upgrade|downgrade|unchanged
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    key_points: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    risk_flags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
