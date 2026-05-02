from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationLogRead(BaseModel):
    notification_id: str
    event_id: str
    instrument_id: Optional[str] = None
    channel: str
    priority: str
    title: str
    body: Optional[str] = None
    status: str
    skip_reason: Optional[str] = None
    dedupe_key: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}
