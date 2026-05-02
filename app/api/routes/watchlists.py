from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.watchlist import Watchlist
from app.schemas.watchlist import WatchlistRead

router = APIRouter()


@router.get("/", response_model=list[WatchlistRead])
def list_watchlists(db: Session = Depends(get_db)):
    return db.query(Watchlist).filter_by(is_active=True).all()
