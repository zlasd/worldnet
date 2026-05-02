from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentEntityMatch(Base):
    __tablename__ = "document_entity_match"

    match_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("source_document.document_id"))
    instrument_id: Mapped[str] = mapped_column(String(36), ForeignKey("instrument.instrument_id"))
    match_type: Mapped[str] = mapped_column(String(50))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_primary_subject: Mapped[bool] = mapped_column(Boolean, default=False)
    matched_text: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
