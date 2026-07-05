from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.instrument import Instrument
from app.models.watchlist import Watchlist, WatchlistItem
from app.schemas.watchlist import WatchlistItemWithInstrumentRead, WatchlistRead

router = APIRouter()


@router.get("/", response_model=list[WatchlistRead])
def list_watchlists(db: Session = Depends(get_db)):
    return db.query(Watchlist).filter_by(is_active=True).all()


@router.get("/{name}/items", response_model=list[WatchlistItemWithInstrumentRead])
def list_watchlist_items(name: str, db: Session = Depends(get_db)):
    watchlist = db.query(Watchlist).filter_by(name=name, is_active=True).first()
    if watchlist is None:
        raise HTTPException(status_code=404, detail="watchlist_not_found")

    rows = (
        db.query(WatchlistItem, Instrument)
        .join(Instrument, Instrument.instrument_id == WatchlistItem.instrument_id)
        .filter(WatchlistItem.watchlist_id == watchlist.watchlist_id)
        .filter(WatchlistItem.is_active.is_(True))
        .order_by(Instrument.market, Instrument.exchange, Instrument.ticker)
        .all()
    )
    return [
        {
            "watchlist_item_id": item.watchlist_item_id,
            "watchlist_id": item.watchlist_id,
            "priority": item.priority,
            "is_holding": item.is_holding,
            "is_active": item.is_active,
            "notes": item.notes,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "instrument": instrument,
        }
        for item, instrument in rows
    ]
