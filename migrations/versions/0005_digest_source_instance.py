"""Separate imported digest history from local digest windows."""

import sqlalchemy as sa
from alembic import op

revision = "0005_digest_source_instance"
down_revision = "0004_index_futures_pe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("digest_log", sa.Column("source_instance", sa.String(100), nullable=True))
    op.create_index("ix_digest_log_source_instance", "digest_log", ["source_instance"])


def downgrade() -> None:
    op.drop_index("ix_digest_log_source_instance", table_name="digest_log")
    op.drop_column("digest_log", "source_instance")
