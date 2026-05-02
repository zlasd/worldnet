from app.models.source_document import SourceDocument
from app.pipelines.dedupe import dedupe_documents
from app.utils.hashing import compute_canonical_hash, compute_content_hash


def _make_doc(title: str, text: str = "") -> SourceDocument:
    return SourceDocument(
        source_name="test",
        source_type="news",
        source_tier="secondary_media",
        title=title,
        language="en",
        raw_text=text,
        content_hash=compute_content_hash(title, text),
        canonical_hash=compute_canonical_hash(title),
        ingestion_status="pending",
    )


def test_no_duplicates(session):
    doc1 = _make_doc("Apple reports earnings", "Revenue up 10%")
    doc2 = _make_doc("Tencent buyback announced", "1000 billion HKD")
    session.add_all([doc1, doc2])
    session.flush()

    total, dups = dedupe_documents(session)
    assert total == 2
    assert dups == 0


def test_duplicate_by_content_hash(session):
    doc1 = _make_doc("Apple reports earnings", "Revenue up 10%")
    doc2 = _make_doc("Apple reports earnings", "Revenue up 10%")
    session.add_all([doc1, doc2])
    session.flush()

    total, dups = dedupe_documents(session)
    assert total == 2
    assert dups == 1


def test_duplicate_by_canonical_hash(session):
    doc1 = _make_doc("Apple Reports Earnings")
    doc2 = _make_doc("apple reports earnings")  # different case -> same canonical
    session.add_all([doc1, doc2])
    session.flush()

    total, dups = dedupe_documents(session)
    assert total == 2
    assert dups == 1
