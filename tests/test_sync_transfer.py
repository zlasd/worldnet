from datetime import datetime, timezone

import pytest

from app.models.digest import DigestItem, DigestLog
from app.models.normalized_event import NormalizedEvent
from app.models.source_document import SourceDocument
from app.sync.transfer import SyncError, build_batch, import_batch, verify_batch


def _document() -> SourceDocument:
    return SourceDocument(
        document_id="doc-overseas-1",
        source_name="bloomberg_markets",
        source_type="rss_news",
        source_tier="tier1",
        title="Markets rally on policy news",
        url="https://example.test/story",
        author="Reporter",
        published_at=datetime(2026, 8, 31, 1, 2, tzinfo=timezone.utc),
        observed_at=datetime(2026, 8, 31, 1, 3, tzinfo=timezone.utc),
        language="en",
        raw_text="A public RSS summary.",
        content_hash="a" * 64,
        canonical_hash="b" * 64,
        metadata_='{"publisher":"Bloomberg","topic":"economy"}',
        ingestion_status="processed",
        created_at=datetime(2026, 8, 31, 1, 3, tzinfo=timezone.utc),
    )


def test_signed_sync_batch_is_idempotent(session):
    document = _document()
    event = NormalizedEvent(
        event_id="event-overseas-1",
        document_id=document.document_id,
        event_type="market_moving",
        event_subtype=None,
        market=None,
        primary_instrument_id=None,
        related_instrument_ids=None,
        event_time=document.published_at,
        detected_at=document.observed_at,
        title=document.title,
        summary=document.raw_text,
        severity="medium",
        sentiment="positive",
        novelty_score=0.8,
        confidence_score=0.5,
        actionability="digest_only",
        source_tier="tier1",
        is_duplicate=False,
        duplicate_of_event_id=None,
        schema_version="1.0",
        created_at=document.created_at,
    )
    digest = DigestLog(
        digest_id="digest-overseas-1",
        digest_type="important_daily",
        window_start=datetime(2026, 8, 30, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 31, 2, tzinfo=timezone.utc),
        outlet_id="none",
        channel="none",
        title="Overseas digest",
        body="Markets rally...",
        status="skipped",
        attempt_count=0,
        created_at=document.created_at,
        updated_at=document.created_at,
    )
    item = DigestItem(
        digest_item_id="digest-item-overseas-1",
        digest_id=digest.digest_id,
        event_id=event.event_id,
        rank=1,
        priority="medium",
        created_at=document.created_at,
    )
    session.add_all([document, event, digest, item])
    session.flush()

    batch = build_batch(session, secret="sync-secret", since=datetime(2026, 8, 30, tzinfo=timezone.utc))

    # Import into a separate in-memory session through the fixture's engine.
    from sqlalchemy.orm import sessionmaker

    other = sessionmaker(bind=session.get_bind())()
    try:
        # The source rows already exist in this test database, so use a fresh
        # database connection only to test idempotence in the same schema.
        counts = import_batch(other, batch, secret="sync-secret", expected_source_instance="oci-overseas")
        assert counts["documents_existing"] == 1
        assert counts["events_existing"] == 1
        assert other.query(SourceDocument).count() == 1
        assert other.query(NormalizedEvent).count() == 1
    finally:
        other.close()


def test_sync_batch_rejects_tampering(session):
    session.add(_document())
    session.flush()
    batch = build_batch(session, secret="sync-secret", source_instance="oci-overseas")
    batch["payload"]["documents"][0]["title"] = "tampered"
    with pytest.raises(SyncError, match="signature verification failed"):
        import_batch(session, batch, secret="sync-secret", expected_source_instance="oci-overseas")


def test_verify_batch_does_not_touch_database(session):
    session.add(_document())
    session.flush()
    batch = build_batch(session, secret="sync-secret", source_instance="oci-overseas")

    payload = verify_batch(batch, secret="sync-secret", expected_source_instance="oci-overseas")

    assert payload["batch_id"] == batch["payload"]["batch_id"]
