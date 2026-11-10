"""Persist official macro release schedules and reminder versions."""

import sqlalchemy as sa
from alembic import op

revision = "0006_macro_calendar"
down_revision = "0005_digest_source_instance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "macro_calendar_entry",
        sa.Column("entry_id", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("schedule_hash", sa.String(64), nullable=False),
        sa.Column("reminded_hash", sa.String(64), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_macro_calendar_entry_provider", "macro_calendar_entry", ["provider"])


def downgrade() -> None:
    op.drop_index("ix_macro_calendar_entry_provider", table_name="macro_calendar_entry")
    op.drop_table("macro_calendar_entry")
