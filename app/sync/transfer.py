"""Signed, idempotent transfer of overseas WorldNet data.

The overseas instance is the producer.  It sends source documents, normalized
events, and digest records to the domestic instance.  Instruments are
deliberately not transferred: the domestic instance owns its watchlists and
instrument master data, so foreign entity matches are imported only when the
referenced instrument already exists locally.
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.digest import DigestItem, DigestLog
from app.models.document_entity_match import DocumentEntityMatch
from app.models.normalized_event import NormalizedEvent
from app.models.source_document import SourceDocument

SYNC_SCHEMA_VERSION = 1
SIGNATURE_ALGORITHM = "hmac-sha256"


class SyncError(ValueError):
    """Raised when a transfer is malformed or fails authentication."""


def _datetime_to_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _datetime_from_json(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SyncError(f"invalid datetime: {value!r}") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sign(payload: dict[str, Any], secret: str) -> str:
    if not secret:
        raise SyncError("sync secret must not be empty")
    return hmac.new(secret.encode("utf-8"), _canonical_json(payload), hashlib.sha256).hexdigest()


def _row_to_dict(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields:
        value = getattr(row, field)
        result[field] = _datetime_to_json(value) if isinstance(value, datetime) else value
    return result


_DOCUMENT_FIELDS = (
    "document_id",
    "source_name",
    "source_type",
    "source_tier",
    "title",
    "url",
    "author",
    "published_at",
    "observed_at",
    "language",
    "raw_text",
    "content_hash",
    "canonical_hash",
    "metadata_",
    "ingestion_status",
    "created_at",
)
_MATCH_FIELDS = (
    "match_id",
    "document_id",
    "instrument_id",
    "match_type",
    "confidence",
    "is_primary_subject",
    "matched_text",
    "created_at",
)
_EVENT_FIELDS = (
    "event_id",
    "document_id",
    "event_type",
    "event_subtype",
    "market",
    "primary_instrument_id",
    "related_instrument_ids",
    "event_time",
    "detected_at",
    "title",
    "summary",
    "severity",
    "sentiment",
    "novelty_score",
    "confidence_score",
    "actionability",
    "source_tier",
    "is_duplicate",
    "duplicate_of_event_id",
    "schema_version",
    "created_at",
)
_DIGEST_FIELDS = (
    "digest_id",
    "digest_type",
    "window_start",
    "window_end",
    "outlet_id",
    "channel",
    "title",
    "body",
    "status",
    "attempt_count",
    "last_attempt_at",
    "next_retry_at",
    "last_error",
    "sent_at",
    "finalized_at",
    "created_at",
    "updated_at",
)
_DIGEST_ITEM_FIELDS = (
    "digest_item_id",
    "digest_id",
    "event_id",
    "rank",
    "priority",
    "created_at",
)


def build_batch(
    session: Session,
    *,
    secret: str,
    source_instance: str = "oci-overseas",
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Build and sign an export batch from a time window.

    Documents are selected by ``observed_at``.  Their dependent matches and
    events are included even when those rows were created a little later, so a
    retry cannot leave dangling references on the receiving instance.
    """

    query = session.query(SourceDocument).order_by(SourceDocument.observed_at, SourceDocument.document_id)
    if since is not None:
        query = query.filter(SourceDocument.observed_at >= since)
    if until is not None:
        query = query.filter(SourceDocument.observed_at < until)
    documents = query.all()
    document_ids = [doc.document_id for doc in documents]

    matches = (
        session.query(DocumentEntityMatch)
        .filter(DocumentEntityMatch.document_id.in_(document_ids))
        .order_by(DocumentEntityMatch.match_id)
        .all()
        if document_ids
        else []
    )
    events = (
        session.query(NormalizedEvent)
        .filter(NormalizedEvent.document_id.in_(document_ids))
        .order_by(NormalizedEvent.detected_at, NormalizedEvent.event_id)
        .all()
        if document_ids
        else []
    )
    event_ids = [event.event_id for event in events]

    # Digest rows are included when they reference an exported event.  This
    # keeps the digest preview useful without copying unrelated domestic logs.
    digest_items = (
        session.query(DigestItem)
        .filter(DigestItem.event_id.in_(event_ids))
        .order_by(DigestItem.digest_item_id)
        .all()
        if event_ids
        else []
    )
    digest_ids = sorted({item.digest_id for item in digest_items})
    digests = (
        session.query(DigestLog).filter(DigestLog.digest_id.in_(digest_ids)).order_by(DigestLog.digest_id).all()
        if digest_ids
        else []
    )

    payload: dict[str, Any] = {
        "schema_version": SYNC_SCHEMA_VERSION,
        "batch_id": str(uuid4()),
        "source_instance": source_instance,
        "generated_at": _datetime_to_json(datetime.now(timezone.utc)),
        "window_start": _datetime_to_json(since),
        "window_end": _datetime_to_json(until),
        "documents": [_row_to_dict(row, _DOCUMENT_FIELDS) for row in documents],
        "matches": [_row_to_dict(row, _MATCH_FIELDS) for row in matches],
        "events": [_row_to_dict(row, _EVENT_FIELDS) for row in events],
        "digests": [_row_to_dict(row, _DIGEST_FIELDS) for row in digests],
        "digest_items": [_row_to_dict(row, _DIGEST_ITEM_FIELDS) for row in digest_items],
    }
    return {
        "payload": payload,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "signature": _sign(payload, secret),
    }


def write_batch(batch: dict[str, Any], output_path: str | Path) -> Path:
    """Write a signed batch as UTF-8 JSON compressed with gzip."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(batch, handle, ensure_ascii=False, sort_keys=True, indent=2)
    return path


def read_batch(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            batch = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"cannot read sync batch {path}: {exc}") from exc
    if not isinstance(batch, dict):
        raise SyncError("sync batch must be a JSON object")
    return batch


def _require(value: dict[str, Any], key: str) -> Any:
    if key not in value:
        raise SyncError(f"sync row is missing {key!r}")
    return value[key]


def _row_datetime(row: dict[str, Any], key: str, *, nullable: bool = True) -> datetime | None:
    value = _require(row, key)
    if value is None and not nullable:
        raise SyncError(f"sync row field {key!r} cannot be null")
    return _datetime_from_json(value)


def _verify_batch(
    batch: dict[str, Any], *, secret: str, expected_source_instance: str | None = None
) -> dict[str, Any]:
    payload = batch.get("payload")
    if not isinstance(payload, dict):
        raise SyncError("sync batch payload is missing")
    if payload.get("schema_version") != SYNC_SCHEMA_VERSION:
        raise SyncError(f"unsupported sync schema version: {payload.get('schema_version')!r}")
    if expected_source_instance and payload.get("source_instance") != expected_source_instance:
        raise SyncError("sync source instance does not match the configured origin")
    if batch.get("signature_algorithm") != SIGNATURE_ALGORITHM:
        raise SyncError("unsupported sync signature algorithm")
    signature = batch.get("signature")
    if not isinstance(signature, str) or not hmac.compare_digest(signature, _sign(payload, secret)):
        raise SyncError("sync signature verification failed")
    return payload


def verify_batch(
    batch: dict[str, Any], *, secret: str, expected_source_instance: str | None = None
) -> dict[str, Any]:
    """Verify a signed batch without importing it into a database."""

    return _verify_batch(
        batch,
        secret=secret,
        expected_source_instance=expected_source_instance,
    )


def _existing_instrument_ids(session: Session) -> set[str]:
    from app.models.instrument import Instrument

    return {row.instrument_id for row in session.query(Instrument.instrument_id).all()}


def import_batch(
    session: Session,
    batch: dict[str, Any],
    *,
    secret: str,
    expected_source_instance: str | None = None,
) -> dict[str, int | str]:
    """Verify and idempotently import one batch into a domestic database."""

    payload = _verify_batch(
        batch, secret=secret, expected_source_instance=expected_source_instance
    )
    documents = payload.get("documents", [])
    matches = payload.get("matches", [])
    events = payload.get("events", [])
    digests = payload.get("digests", [])
    digest_items = payload.get("digest_items", [])
    for name, rows in (
        ("documents", documents),
        ("matches", matches),
        ("events", events),
        ("digests", digests),
        ("digest_items", digest_items),
    ):
        if not isinstance(rows, list):
            raise SyncError(f"sync payload field {name!r} must be a list")

    counts = {
        "batch_id": str(_require(payload, "batch_id")),
        "documents_added": 0,
        "documents_existing": 0,
        "matches_added": 0,
        "matches_skipped": 0,
        "events_added": 0,
        "events_existing": 0,
        "events_skipped": 0,
        "digests_added": 0,
        "digests_existing": 0,
        "digest_items_added": 0,
        "digest_items_skipped": 0,
    }

    document_id_map: dict[str, str] = {}
    for row in documents:
        incoming_id = str(_require(row, "document_id"))
        existing = session.get(SourceDocument, incoming_id)
        if existing:
            document_id_map[incoming_id] = existing.document_id
            counts["documents_existing"] += 1
            continue

        content_hash = row.get("content_hash")
        existing_by_hash = (
            session.query(SourceDocument).filter_by(content_hash=content_hash).first()
            if content_hash
            else None
        )
        if existing_by_hash:
            document_id_map[incoming_id] = existing_by_hash.document_id
            counts["documents_existing"] += 1
            continue

        session.add(
            SourceDocument(
                document_id=incoming_id,
                source_name=str(_require(row, "source_name")),
                source_type=str(_require(row, "source_type")),
                source_tier=str(_require(row, "source_tier")),
                title=str(_require(row, "title")),
                url=row.get("url"),
                author=row.get("author"),
                published_at=_row_datetime(row, "published_at"),
                observed_at=_row_datetime(row, "observed_at", nullable=False),
                language=str(_require(row, "language")),
                raw_text=row.get("raw_text"),
                content_hash=content_hash,
                canonical_hash=row.get("canonical_hash"),
                metadata_=row.get("metadata_"),
                ingestion_status=str(_require(row, "ingestion_status")),
                created_at=_row_datetime(row, "created_at", nullable=False),
            )
        )
        document_id_map[incoming_id] = incoming_id
        counts["documents_added"] += 1
    session.flush()

    instrument_ids = _existing_instrument_ids(session)
    for row in matches:
        incoming_id = str(_require(row, "match_id"))
        if session.get(DocumentEntityMatch, incoming_id):
            counts["matches_skipped"] += 1
            continue
        document_id = document_id_map.get(str(_require(row, "document_id")))
        instrument_id = str(_require(row, "instrument_id"))
        if not document_id or instrument_id not in instrument_ids:
            counts["matches_skipped"] += 1
            continue
        session.add(
            DocumentEntityMatch(
                match_id=incoming_id,
                document_id=document_id,
                instrument_id=instrument_id,
                match_type=str(_require(row, "match_type")),
                confidence=float(_require(row, "confidence")),
                is_primary_subject=bool(_require(row, "is_primary_subject")),
                matched_text=row.get("matched_text"),
                created_at=_row_datetime(row, "created_at", nullable=False),
            )
        )
        counts["matches_added"] += 1
    session.flush()

    event_id_map: dict[str, str] = {}
    for row in events:
        incoming_id = str(_require(row, "event_id"))
        existing = session.get(NormalizedEvent, incoming_id)
        if existing:
            event_id_map[incoming_id] = existing.event_id
            counts["events_existing"] += 1
            continue
        document_id = document_id_map.get(str(_require(row, "document_id")))
        if not document_id:
            counts["events_skipped"] += 1
            continue

        primary_instrument_id = row.get("primary_instrument_id")
        if primary_instrument_id not in instrument_ids:
            primary_instrument_id = None
        related_ids: str | None = row.get("related_instrument_ids")
        if related_ids:
            try:
                parsed_related = json.loads(related_ids)
                if isinstance(parsed_related, list):
                    related_ids = json.dumps(
                        [item for item in parsed_related if str(item) in instrument_ids]
                    ) or None
            except (TypeError, json.JSONDecodeError):
                related_ids = None

        duplicate_of = row.get("duplicate_of_event_id")
        if duplicate_of and not session.get(NormalizedEvent, str(duplicate_of)):
            duplicate_of = None
        session.add(
            NormalizedEvent(
                event_id=incoming_id,
                document_id=document_id,
                event_type=str(_require(row, "event_type")),
                event_subtype=row.get("event_subtype"),
                market=row.get("market"),
                primary_instrument_id=primary_instrument_id,
                related_instrument_ids=related_ids,
                event_time=_row_datetime(row, "event_time"),
                detected_at=_row_datetime(row, "detected_at", nullable=False),
                title=str(_require(row, "title")),
                summary=row.get("summary"),
                severity=str(_require(row, "severity")),
                sentiment=str(_require(row, "sentiment")),
                novelty_score=float(_require(row, "novelty_score")),
                confidence_score=float(_require(row, "confidence_score")),
                actionability=str(_require(row, "actionability")),
                source_tier=row.get("source_tier"),
                is_duplicate=bool(_require(row, "is_duplicate")),
                duplicate_of_event_id=duplicate_of,
                schema_version=str(_require(row, "schema_version")),
                created_at=_row_datetime(row, "created_at", nullable=False),
            )
        )
        event_id_map[incoming_id] = incoming_id
        counts["events_added"] += 1
    session.flush()

    digest_id_map: dict[str, str] = {}
    for row in digests:
        incoming_id = str(_require(row, "digest_id"))
        existing = session.get(DigestLog, incoming_id)
        if existing:
            digest_id_map[incoming_id] = existing.digest_id
            counts["digests_existing"] += 1
            continue
        window_start = _row_datetime(row, "window_start", nullable=False)
        window_end = _row_datetime(row, "window_end", nullable=False)
        existing_unique = (
            session.query(DigestLog)
            .filter_by(
                digest_type=str(_require(row, "digest_type")),
                window_start=window_start,
                window_end=window_end,
                outlet_id=str(_require(row, "outlet_id")),
            )
            .first()
        )
        if existing_unique:
            digest_id_map[incoming_id] = existing_unique.digest_id
            counts["digests_existing"] += 1
            continue
        session.add(
            DigestLog(
                digest_id=incoming_id,
                digest_type=str(_require(row, "digest_type")),
                window_start=window_start,
                window_end=window_end,
                outlet_id=str(_require(row, "outlet_id")),
                channel=str(_require(row, "channel")),
                title=str(_require(row, "title")),
                body=row.get("body"),
                status=str(_require(row, "status")),
                attempt_count=int(_require(row, "attempt_count")),
                last_attempt_at=_row_datetime(row, "last_attempt_at"),
                next_retry_at=_row_datetime(row, "next_retry_at"),
                last_error=row.get("last_error"),
                sent_at=_row_datetime(row, "sent_at"),
                finalized_at=_row_datetime(row, "finalized_at"),
                created_at=_row_datetime(row, "created_at", nullable=False),
                updated_at=_row_datetime(row, "updated_at", nullable=False),
            )
        )
        digest_id_map[incoming_id] = incoming_id
        counts["digests_added"] += 1
    session.flush()

    for row in digest_items:
        incoming_id = str(_require(row, "digest_item_id"))
        if session.get(DigestItem, incoming_id):
            counts["digest_items_skipped"] += 1
            continue
        digest_id = digest_id_map.get(str(_require(row, "digest_id")))
        event_id = event_id_map.get(str(_require(row, "event_id")))
        if not digest_id or not event_id:
            counts["digest_items_skipped"] += 1
            continue
        session.add(
            DigestItem(
                digest_item_id=incoming_id,
                digest_id=digest_id,
                event_id=event_id,
                rank=int(_require(row, "rank")),
                priority=str(_require(row, "priority")),
                created_at=_row_datetime(row, "created_at", nullable=False),
            )
        )
        counts["digest_items_added"] += 1
    session.flush()
    return counts
