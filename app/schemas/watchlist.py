from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WatchlistBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True


class WatchlistCreate(WatchlistBase):
    pass


class WatchlistRead(WatchlistBase):
    watchlist_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WatchlistItemBase(BaseModel):
    watchlist_id: str
    instrument_id: str
    priority: str = "medium"
    is_holding: bool = False
    notes: Optional[str] = None


class WatchlistItemCreate(WatchlistItemBase):
    pass


class WatchlistItemRead(WatchlistItemBase):
    watchlist_item_id: str
    created_at: datetime

    model_config = {"from_attributes": True}
