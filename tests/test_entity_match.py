import json

from app.models.instrument import Instrument
from app.models.source_document import SourceDocument
from app.pipelines.entity_match import match_document_to_instruments, run_entity_matching


def _make_instrument(ticker: str, company_name: str, local_name: str = None, aliases: list = None) -> Instrument:
    return Instrument(
        market="US",
        ticker=ticker,
        exchange="NASDAQ",
        company_name=company_name,
        local_name=local_name,
        aliases=json.dumps(aliases) if aliases else None,
        currency="USD",
        is_active=True,
    )


def _make_doc(title: str, raw_text: str = "") -> SourceDocument:
    return SourceDocument(
        source_name="test",
        source_type="news",
        source_tier="secondary_media",
        title=title,
        language="en",
        raw_text=raw_text,
        ingestion_status="pending",
    )


def test_ticker_match(session):
    instr = _make_instrument("AAPL", "Apple Inc.")
    session.add(instr)
    session.flush()

    doc = _make_doc("AAPL reports strong Q2 earnings")
    session.add(doc)
    session.flush()

    matches = match_document_to_instruments(doc, [instr])
    assert len(matches) == 1
    assert matches[0].match_type == "explicit_ticker"
    assert matches[0].confidence == 0.95


def test_company_name_match(session):
    instr = _make_instrument("AAPL", "Apple Inc.")
    session.add(instr)
    session.flush()

    doc = _make_doc("Apple Inc. announces new product lineup")
    session.add(doc)
    session.flush()

    matches = match_document_to_instruments(doc, [instr])
    assert len(matches) == 1
    assert matches[0].match_type == "company_name"
    assert matches[0].confidence == 0.85


def test_alias_match(session):
    instr = _make_instrument("0700", "Tencent Holdings Limited", aliases=["腾讯", "Tencent"])
    session.add(instr)
    session.flush()

    doc = _make_doc("腾讯宣布回购计划")
    session.add(doc)
    session.flush()

    matches = match_document_to_instruments(doc, [instr])
    assert len(matches) == 1
    assert matches[0].match_type == "alias"
    assert matches[0].confidence == 0.75


def test_no_match(session):
    instr = _make_instrument("MSFT", "Microsoft Corporation")
    session.add(instr)
    session.flush()

    doc = _make_doc("Apple announces new iPhone model")
    session.add(doc)
    session.flush()

    matches = match_document_to_instruments(doc, [instr])
    assert len(matches) == 0


def test_run_entity_matching(session):
    instr = _make_instrument("AAPL", "Apple Inc.", aliases=["Apple"])
    session.add(instr)
    session.flush()

    doc = _make_doc("Apple Inc. Reports Second Quarter Results")
    session.add(doc)
    session.flush()

    count = run_entity_matching(session)
    assert count >= 1
