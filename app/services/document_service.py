from sqlalchemy.orm import Session

from app.models.source_document import SourceDocument


def get_documents(
    session: Session,
    status: str | None = None,
    limit: int = 50,
) -> list[SourceDocument]:
    q = session.query(SourceDocument)
    if status:
        q = q.filter(SourceDocument.ingestion_status == status)
    return q.order_by(SourceDocument.created_at.desc()).limit(limit).all()
