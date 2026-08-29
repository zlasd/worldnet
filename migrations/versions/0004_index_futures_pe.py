"""store official index rolling PE alongside basis snapshots

Revision ID: 0004_index_futures_pe
Revises: 0003_index_futures_monitor
Create Date: 2026-08-29 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_index_futures_pe"
down_revision: Union[str, None] = "0003_index_futures_monitor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "index_futures_basis_snapshot",
        sa.Column("spot_pe", sa.Numeric(18, 6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("index_futures_basis_snapshot", "spot_pe")
