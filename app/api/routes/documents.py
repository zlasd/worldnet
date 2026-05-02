from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.source_document import SourceDocumentRead
from app.services.document_service import get_documents

router = APIRouter()


@router.get("/", response_model=list[SourceDocumentRead])
def list_documents(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    return get_documents(db, status=status, limit=limit)
