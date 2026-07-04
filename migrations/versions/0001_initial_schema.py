"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-05 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "instrument",
        sa.Column("instrument_id", sa.String(length=36), nullable=False),
        sa.Column("market", sa.String(length=10), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("exchange", sa.String(length=50), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("local_name", sa.String(length=200), nullable=True),
        sa.Column("aliases", sa.Text(), nullable=True),
        sa.Column("sector", sa.String(length=100), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("instrument_id"),
    )
    op.create_index(op.f("ix_instrument_ticker"), "instrument", ["ticker"], unique=False)

    op.create_table(
        "source_document",
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("source_name", sa.String(length=200), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_tier", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=True),
        sa.Column("author", sa.String(length=200), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("canonical_hash", sa.String(length=64), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("ingestion_status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_index(
        op.f("ix_source_document_canonical_hash"),
        "source_document",
        ["canonical_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_document_content_hash"),
        "source_document",
        ["content_hash"],
        unique=False,
    )

    op.create_table(
        "watchlist",
        sa.Column("watchlist_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("watchlist_id"),
    )

    op.create_table(
        "document_entity_match",
        sa.Column("match_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=False),
        sa.Column("match_type", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("is_primary_subject", sa.Boolean(), nullable=False),
        sa.Column("matched_text", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["source_document.document_id"]),
        sa.ForeignKeyConstraint(["instrument_id"], ["instrument.instrument_id"]),
        sa.PrimaryKeyConstraint("match_id"),
    )

    op.create_table(
        "normalized_event",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("event_subtype", sa.String(length=50), nullable=True),
        sa.Column("market", sa.String(length=10), nullable=True),
        sa.Column("primary_instrument_id", sa.String(length=36), nullable=True),
        sa.Column("related_instrument_ids", sa.Text(), nullable=True),
        sa.Column("event_time", sa.DateTime(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("sentiment", sa.String(length=20), nullable=False),
        sa.Column("novelty_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("actionability", sa.String(length=20), nullable=False),
        sa.Column("source_tier", sa.String(length=50), nullable=True),
        sa.Column("is_duplicate", sa.Boolean(), nullable=False),
        sa.Column("duplicate_of_event_id", sa.String(length=36), nullable=True),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["source_document.document_id"]),
        sa.ForeignKeyConstraint(["primary_instrument_id"], ["instrument.instrument_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )

    op.create_table(
        "watchlist_item",
        sa.Column("watchlist_item_id", sa.String(length=36), nullable=False),
        sa.Column("watchlist_id", sa.String(length=36), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("is_holding", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instrument.instrument_id"]),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlist.watchlist_id"]),
        sa.PrimaryKeyConstraint("watchlist_item_id"),
    )

    op.create_table(
        "digest_log",
        sa.Column("digest_id", sa.String(length=36), nullable=False),
        sa.Column("digest_type", sa.String(length=50), nullable=False),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("window_end", sa.DateTime(), nullable=False),
        sa.Column("outlet_id", sa.String(length=100), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("digest_id"),
        sa.UniqueConstraint(
            "digest_type",
            "window_start",
            "window_end",
            "outlet_id",
            name="uq_digest_log_window_outlet",
        ),
    )
    op.create_index(op.f("ix_digest_log_outlet_id"), "digest_log", ["outlet_id"], unique=False)

    op.create_table(
        "digest_item",
        sa.Column("digest_item_id", sa.String(length=36), nullable=False),
        sa.Column("digest_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("priority", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["digest_id"], ["digest_log.digest_id"]),
        sa.ForeignKeyConstraint(["event_id"], ["normalized_event.event_id"]),
        sa.PrimaryKeyConstraint("digest_item_id"),
        sa.UniqueConstraint("digest_id", "event_id", name="uq_digest_item_digest_event"),
    )

    op.create_table(
        "event_impact",
        sa.Column("impact_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=True),
        sa.Column("impact_horizon", sa.String(length=20), nullable=True),
        sa.Column("impact_strength", sa.Float(), nullable=True),
        sa.Column("thesis_change", sa.String(length=20), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("key_points", sa.Text(), nullable=True),
        sa.Column("risk_flags", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["normalized_event.event_id"]),
        sa.ForeignKeyConstraint(["instrument_id"], ["instrument.instrument_id"]),
        sa.PrimaryKeyConstraint("impact_id"),
    )

    op.create_table(
        "notification_log",
        sa.Column("notification_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("instrument_id", sa.String(length=36), nullable=True),
        sa.Column("outlet_id", sa.String(length=100), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.String(length=10), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("skip_reason", sa.String(length=200), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["normalized_event.event_id"]),
        sa.ForeignKeyConstraint(["instrument_id"], ["instrument.instrument_id"]),
        sa.PrimaryKeyConstraint("notification_id"),
        sa.UniqueConstraint("event_id", "outlet_id", name="uq_notification_log_event_outlet"),
    )
    op.create_index(
        op.f("ix_notification_log_dedupe_key"),
        "notification_log",
        ["dedupe_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_log_outlet_id"),
        "notification_log",
        ["outlet_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_notification_log_outlet_id"), table_name="notification_log")
    op.drop_index(op.f("ix_notification_log_dedupe_key"), table_name="notification_log")
    op.drop_table("notification_log")
    op.drop_table("event_impact")
    op.drop_table("digest_item")
    op.drop_index(op.f("ix_digest_log_outlet_id"), table_name="digest_log")
    op.drop_table("digest_log")
    op.drop_table("watchlist_item")
    op.drop_table("normalized_event")
    op.drop_table("document_entity_match")
    op.drop_table("watchlist")
    op.drop_index(op.f("ix_source_document_content_hash"), table_name="source_document")
    op.drop_index(op.f("ix_source_document_canonical_hash"), table_name="source_document")
    op.drop_table("source_document")
    op.drop_index(op.f("ix_instrument_ticker"), table_name="instrument")
    op.drop_table("instrument")
