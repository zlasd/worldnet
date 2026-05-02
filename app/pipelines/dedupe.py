from sqlalchemy.orm import Session

from app.models.source_document import SourceDocument


def dedupe_documents(session: Session) -> tuple[int, int]:
    pending = session.query(SourceDocument).filter_by(ingestion_status="pending").all()
    dup_count = 0
    seen_content: dict[str, str] = {}
    seen_canonical: dict[str, str] = {}

    for doc in pending:
        is_dup = False
        if doc.content_hash and doc.content_hash in seen_content:
            doc.ingestion_status = "duplicate"
            is_dup = True
        elif doc.canonical_hash and doc.canonical_hash in seen_canonical:
            doc.ingestion_status = "duplicate"
            is_dup = True

        if not is_dup:
            if doc.content_hash:
                seen_content[doc.content_hash] = doc.document_id
            if doc.canonical_hash:
                seen_canonical[doc.canonical_hash] = doc.document_id
        else:
            dup_count += 1

    session.flush()
    return len(pending), dup_count
