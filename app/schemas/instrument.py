from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class InstrumentBase(BaseModel):
    market: str
    ticker: str
    exchange: str
    company_name: str
    local_name: Optional[str] = None
    aliases: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    currency: str
    is_active: bool = True


class InstrumentCreate(InstrumentBase):
    pass


class InstrumentRead(InstrumentBase):
    instrument_id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
