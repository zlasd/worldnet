"""Bounded repair of derived news fields; never changes sent digest history."""

from collections import Counter
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.normalized_event import NormalizedEvent
from app.models.source_document import SourceDocument
from app.pipelines.normalize_event import classify_document
from app.rules.priority_rules import determine_notification_priority

MACRO_TYPES = {"macro_release_reminder", "macro_data_release", "central_bank_decision"}


def reclassify_events(
    session: Session, *, since: datetime, until: datetime, apply: bool = False
) -> dict:
    if since.tzinfo is not None or until.tzinfo is not None or since >= until:
        raise ValueError("reclassification requires an increasing UTC-naive interval")
    rows = (
        session.query(NormalizedEvent, SourceDocument)
        .join(SourceDocument, SourceDocument.document_id == NormalizedEvent.document_id)
        .filter(NormalizedEvent.detected_at >= since, NormalizedEvent.detected_at < until)
        .filter(NormalizedEvent.event_type.notin_(MACRO_TYPES))
        .filter(SourceDocument.source_type.notin_({"macro_data", "macro_calendar"}))
        .all()
    )
    changed = 0
    before: Counter = Counter()
    after: Counter = Counter()
    for event, document in rows:
        fields = classify_document(document)
        before[determine_notification_priority(event, set()).value] += 1
        # Transient preview: the dry run must not dirty persistent ORM objects.
        preview = NormalizedEvent(**fields, source_tier=event.source_tier)
        after[determine_notification_priority(preview, set()).value] += 1
        if any(getattr(event, key) != value for key, value in fields.items()):
            changed += 1
            if apply:
                for key, value in fields.items():
                    setattr(event, key, value)
    if apply:
        session.flush()
    return {"scanned": len(rows), "changed": changed, "before": dict(before), "after": dict(after), "applied": apply}
