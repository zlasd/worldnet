from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DigestLogRead(BaseModel):
    digest_id: str
    digest_type: str
    window_start: datetime
    window_end: datetime
    outlet_id: str
    channel: str
    title: str
    body: Optional[str] = None
    status: str
    attempt_count: int
    last_attempt_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    last_error: Optional[str] = None
    sent_at: Optional[datetime] = None
    finalized_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DigestItemRead(BaseModel):
    digest_item_id: str
    digest_id: str
    event_id: str
    rank: int
    priority: str
    created_at: datetime

    model_config = {"from_attributes": True}
