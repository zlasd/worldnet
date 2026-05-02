from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SourceDocumentRead(BaseModel):
    document_id: str
    source_name: str
    source_type: str
    source_tier: str
    title: str
    url: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    observed_at: datetime
    language: str
    ingestion_status: str
    content_hash: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
