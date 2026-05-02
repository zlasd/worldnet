from datetime import datetime

from pydantic import BaseModel


class DocumentEntityMatchRead(BaseModel):
    match_id: str
    document_id: str
    instrument_id: str
    match_type: str
    confidence: float
    is_primary_subject: bool
    matched_text: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
