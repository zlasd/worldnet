from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.normalized_event import NormalizedEventRead
from app.services.event_service import get_events

router = APIRouter()


@router.get("/", response_model=list[NormalizedEventRead])
def list_events(
    severity: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    return get_events(db, severity=severity, event_type=event_type, limit=limit)
