from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MacroCalendarEntry(Base):
    __tablename__ = "macro_calendar_entry"

    # Stable provider + release identity; a reschedule must not create a new entry.
    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), index=True)
    payload: Mapped[str] = mapped_column(Text)
    schedule_hash: Mapped[str] = mapped_column(String(64))
    reminded_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime)
