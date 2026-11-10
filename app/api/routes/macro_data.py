from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.macro_data.service import observations, snapshots

router = APIRouter()


@router.get("/observations")
def list_observations(
    series_id: str | None = None,
    country: Literal["CN", "US"] | None = None,
    period: str | None = None,
    history: bool = False,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return observations(db, series_id=series_id, country=country, period=period, history=history, limit=limit)


@router.get("/releases")
def list_releases(
    country: Literal["CN", "US"] | None = None,
    history: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return [{"document_id": doc.document_id, "observed_at": doc.observed_at,
             "notice_kind": metadata["notice_kind"], **release.model_dump(mode="json")}
            for doc, release, metadata in snapshots(db, history=history)
            if not country or release.country == country][:limit]
