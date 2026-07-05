"""watchlist management constraints

Revision ID: 0002_watchlist_management
Revises: 0001_initial_schema
Create Date: 2026-07-05 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_watchlist_management"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("instrument") as batch_op:
        batch_op.create_unique_constraint(
            "uq_instrument_market_exchange_ticker",
            ["market", "exchange", "ticker"],
        )

    with op.batch_alter_table("watchlist") as batch_op:
        batch_op.create_unique_constraint("uq_watchlist_name", ["name"])

    with op.batch_alter_table("watchlist_item") as batch_op:
        batch_op.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_watchlist_item_watchlist_instrument",
            ["watchlist_id", "instrument_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("watchlist_item") as batch_op:
        batch_op.drop_constraint("uq_watchlist_item_watchlist_instrument", type_="unique")
        batch_op.drop_column("updated_at")
        batch_op.drop_column("is_active")

    with op.batch_alter_table("watchlist") as batch_op:
        batch_op.drop_constraint("uq_watchlist_name", type_="unique")

    with op.batch_alter_table("instrument") as batch_op:
        batch_op.drop_constraint("uq_instrument_market_exchange_ticker", type_="unique")
