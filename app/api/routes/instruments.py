from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.instrument import InstrumentRead
from app.services.instrument_service import get_instruments

router = APIRouter()


@router.get("/", response_model=list[InstrumentRead])
def list_instruments(
    market: str | None = Query(default=None),
    ticker: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    return get_instruments(db, market=market, ticker=ticker, limit=limit)
