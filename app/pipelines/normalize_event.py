import json

from sqlalchemy.orm import Session

from app.models.document_entity_match import DocumentEntityMatch
from app.models.instrument import Instrument
from app.models.normalized_event import NormalizedEvent
from app.models.source_document import SourceDocument
from app.rules.keyword_rules import detect_event_type, detect_sentiment
from app.rules.priority_rules import determine_actionability, determine_severity


def normalize_events(session: Session) -> list[NormalizedEvent]:
    docs = session.query(SourceDocument).filter(
        SourceDocument.ingestion_status == "pending"
    ).all()

    events = []
    for doc in docs:
        primary_match = (
            session.query(DocumentEntityMatch)
            .filter_by(document_id=doc.document_id, is_primary_subject=True)
            .order_by(DocumentEntityMatch.confidence.desc())
            .first()
        )

        all_matches = (
            session.query(DocumentEntityMatch)
            .filter_by(document_id=doc.document_id)
            .all()
        )

        related_ids = [
            m.instrument_id for m in all_matches
            if primary_match is None or m.instrument_id != primary_match.instrument_id
        ]

        event_type, event_subtype = detect_event_type(
            doc.title, doc.raw_text or "", doc.source_type
        )
        sentiment = detect_sentiment(doc.title, doc.raw_text or "")
        severity = determine_severity(event_type, doc.source_tier)
        actionability = determine_actionability(severity, doc.source_tier)

        market = None
        if primary_match:
            instr = session.get(Instrument, primary_match.instrument_id)
            market = instr.market if instr else None

        event = NormalizedEvent(
            document_id=doc.document_id,
            event_type=event_type,
            event_subtype=event_subtype,
            market=market,
            primary_instrument_id=primary_match.instrument_id if primary_match else None,
            related_instrument_ids=json.dumps(related_ids) if related_ids else None,
            event_time=doc.published_at,
            title=doc.title,
            severity=severity,
            sentiment=sentiment,
            actionability=actionability,
            source_tier=doc.source_tier,
            confidence_score=primary_match.confidence if primary_match else 0.5,
        )
        session.add(event)
        doc.ingestion_status = "processed"
        events.append(event)

    session.flush()
    return events
