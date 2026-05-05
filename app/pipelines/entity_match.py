import json
import re

from sqlalchemy.orm import Session

from app.models.document_entity_match import DocumentEntityMatch
from app.models.instrument import Instrument
from app.models.source_document import SourceDocument


def _normalize_text(text: str) -> str:
    return text.lower()


def match_document_to_instruments(
    doc: SourceDocument, instruments: list[Instrument]
) -> list[DocumentEntityMatch]:
    matches = []
    text = f"{doc.title} {doc.author or ''} {doc.raw_text or ''}".strip()
    text_lower = _normalize_text(text)

    for instr in instruments:
        matched_text = None
        match_type = None
        confidence = 0.0

        ticker_pattern = r"\b" + re.escape(instr.ticker.upper()) + r"\b"
        if re.search(ticker_pattern, text.upper()):
            matched_text = instr.ticker
            match_type = "explicit_ticker"
            confidence = 0.95
        elif instr.company_name.lower() in text_lower:
            matched_text = instr.company_name
            match_type = "company_name"
            confidence = 0.85
        elif instr.local_name and instr.local_name.lower() in text_lower:
            matched_text = instr.local_name
            match_type = "company_name"
            confidence = 0.85
        else:
            aliases: list[str] = []
            if instr.aliases:
                try:
                    aliases = json.loads(instr.aliases)
                except Exception:
                    aliases = [instr.aliases]
            for alias in aliases:
                if alias.lower() in text_lower:
                    matched_text = alias
                    match_type = "alias"
                    confidence = 0.75
                    break

        if match_type:
            matches.append(
                DocumentEntityMatch(
                    document_id=doc.document_id,
                    instrument_id=instr.instrument_id,
                    match_type=match_type,
                    confidence=confidence,
                    is_primary_subject=(confidence >= 0.85),
                    matched_text=matched_text,
                )
            )

    return matches


def run_entity_matching(session: Session) -> int:
    docs = session.query(SourceDocument).filter(
        SourceDocument.ingestion_status == "pending"
    ).all()
    instruments = session.query(Instrument).filter_by(is_active=True).all()

    total_matches = 0
    for doc in docs:
        matches = match_document_to_instruments(doc, instruments)
        for m in matches:
            session.add(m)
        total_matches += len(matches)

    session.flush()
    return total_matches
