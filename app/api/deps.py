from hmac import compare_digest
from typing import Generator

from fastapi import Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    key: str | None = Query(default=None),
) -> None:
    configured_key = settings.api_access_key
    if not configured_key:
        return

    provided_key = x_api_key or key
    if provided_key and compare_digest(provided_key, configured_key):
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key.",
    )
