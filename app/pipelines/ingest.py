import json

from dateutil import parser as dp
from sqlalchemy.orm import Session

from app.adapters.base import BaseAdapter
from app.models.source_document import SourceDocument
from app.utils.hashing import compute_canonical_hash, compute_content_hash


def ingest_documents(adapter: BaseAdapter, session: Session) -> list[SourceDocument]:
    raw_docs = adapter.run()
    saved = []
    for raw in raw_docs:
        content_hash = compute_content_hash(raw.title, raw.raw_text)
        canonical_hash = compute_canonical_hash(raw.title)

        existing = session.query(SourceDocument).filter_by(content_hash=content_hash).first()
        if existing:
            continue

        pub_at = None
        if raw.published_at:
            try:
                pub_at = dp.parse(raw.published_at)
            except Exception:
                pass

        doc = SourceDocument(
            source_name=adapter.source_name,
            source_type=adapter.source_type,
            source_tier=adapter.source_tier,
            title=raw.title,
            url=raw.url,
            author=raw.author,
            published_at=pub_at,
            language=raw.language,
            raw_text=raw.raw_text,
            content_hash=content_hash,
            canonical_hash=canonical_hash,
            metadata_=json.dumps(adapter.normalize_metadata(raw)),
            ingestion_status="pending",
        )
        session.add(doc)
        saved.append(doc)

    session.flush()
    return saved
