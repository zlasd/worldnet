from sqlalchemy.orm import Session

from app.adapters.base import BaseAdapter
from app.pipelines.dedupe import dedupe_documents
from app.pipelines.entity_match import run_entity_matching
from app.pipelines.ingest import ingest_documents
from app.pipelines.normalize_event import normalize_events


def run_full_pipeline(adapter: BaseAdapter, session: Session) -> dict:
    ingested = ingest_documents(adapter, session)
    _total, dups = dedupe_documents(session)
    match_count = run_entity_matching(session)
    events = normalize_events(session)

    return {
        "ingested": len(ingested),
        "deduped": dups,
        "entity_matches": match_count,
        "events_created": len(events),
        "notifications_prepared": 0,
    }
