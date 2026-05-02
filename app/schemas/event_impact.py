from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class EventImpactRead(BaseModel):
    impact_id: str
    event_id: str
    instrument_id: str
    direction: Optional[str] = None
    impact_horizon: Optional[str] = None
    impact_strength: Optional[float] = None
    thesis_change: Optional[str] = None
    reasoning: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
