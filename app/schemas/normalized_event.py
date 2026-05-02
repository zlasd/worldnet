from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NormalizedEventRead(BaseModel):
    event_id: str
    document_id: str
    event_type: str
    event_subtype: Optional[str] = None
    market: Optional[str] = None
    primary_instrument_id: Optional[str] = None
    event_time: Optional[datetime] = None
    detected_at: datetime
    title: str
    summary: Optional[str] = None
    severity: str
    sentiment: str
    novelty_score: float
    confidence_score: float
    actionability: str
    source_tier: Optional[str] = None
    is_duplicate: bool
    schema_version: str
    created_at: datetime

    model_config = {"from_attributes": True}
