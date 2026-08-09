"""index futures basis monitor and paper strategy

Revision ID: 0003_index_futures_monitor
Revises: 0002_watchlist_management
Create Date: 2026-08-10 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_index_futures_monitor"
down_revision: Union[str, None] = "0002_watchlist_management"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "index_futures_basis_snapshot",
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("product", sa.String(length=2), nullable=False),
        sa.Column("contract_code", sa.String(length=10), nullable=False),
        sa.Column("index_code", sa.String(length=6), nullable=False),
        sa.Column("futures_open", sa.Numeric(18, 6), nullable=False),
        sa.Column("futures_close", sa.Numeric(18, 6), nullable=False),
        sa.Column("settlement", sa.Numeric(18, 6), nullable=True),
        sa.Column("spot_close", sa.Numeric(18, 6), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=False),
        sa.Column("days_to_expiry", sa.Integer(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("open_interest", sa.BigInteger(), nullable=False),
        sa.Column("discount_points", sa.Numeric(18, 6), nullable=False),
        sa.Column("discount_rate", sa.Numeric(18, 10), nullable=False),
        sa.Column("annualized_discount_rate", sa.Numeric(18, 10), nullable=True),
        sa.Column("source_name", sa.String(length=50), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id"),
        sa.UniqueConstraint(
            "trade_date", "contract_code", name="uq_index_futures_basis_date_contract"
        ),
    )
    op.create_index("ix_index_futures_basis_snapshot_trade_date", "index_futures_basis_snapshot", ["trade_date"])
    op.create_index("ix_index_futures_basis_snapshot_product", "index_futures_basis_snapshot", ["product"])

    op.create_table(
        "index_futures_paper_portfolio",
        sa.Column("product", sa.String(length=2), nullable=False),
        sa.Column("index_code", sa.String(length=6), nullable=False),
        sa.Column("multiplier", sa.Integer(), nullable=False),
        sa.Column("initial_nav", sa.Numeric(20, 6), nullable=False),
        sa.Column("nav", sa.Numeric(20, 6), nullable=False),
        sa.Column("current_contract", sa.String(length=10), nullable=True),
        sa.Column("quantity", sa.Numeric(24, 10), nullable=False),
        sa.Column("pending_contract", sa.String(length=10), nullable=True),
        sa.Column("pending_signal_date", sa.Date(), nullable=True),
        sa.Column("pending_reason", sa.String(length=100), nullable=True),
        sa.Column("pending_score", sa.Numeric(18, 10), nullable=True),
        sa.Column("benchmark_start_close", sa.Numeric(18, 6), nullable=True),
        sa.Column("cumulative_cost", sa.Numeric(20, 6), nullable=False),
        sa.Column("roll_count", sa.Integer(), nullable=False),
        sa.Column("peak_nav", sa.Numeric(20, 6), nullable=False),
        sa.Column("max_drawdown", sa.Numeric(18, 10), nullable=False),
        sa.Column("last_processed_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("product"),
    )

    op.create_table(
        "index_futures_paper_nav",
        sa.Column("nav_id", sa.String(length=36), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("product", sa.String(length=2), nullable=False),
        sa.Column("contract_code", sa.String(length=10), nullable=True),
        sa.Column("nav", sa.Numeric(20, 6), nullable=False),
        sa.Column("daily_pnl", sa.Numeric(20, 6), nullable=False),
        sa.Column("daily_return", sa.Numeric(18, 10), nullable=False),
        sa.Column("benchmark_close", sa.Numeric(18, 6), nullable=False),
        sa.Column("benchmark_nav", sa.Numeric(20, 6), nullable=False),
        sa.Column("position_notional", sa.Numeric(20, 6), nullable=False),
        sa.Column("cumulative_cost", sa.Numeric(20, 6), nullable=False),
        sa.Column("drawdown", sa.Numeric(18, 10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("nav_id"),
        sa.UniqueConstraint("trade_date", "product", name="uq_index_futures_paper_nav_date_product"),
    )
    op.create_index("ix_index_futures_paper_nav_trade_date", "index_futures_paper_nav", ["trade_date"])
    op.create_index("ix_index_futures_paper_nav_product", "index_futures_paper_nav", ["product"])

    op.create_table(
        "index_futures_paper_trade",
        sa.Column("trade_id", sa.String(length=36), nullable=False),
        sa.Column("product", sa.String(length=2), nullable=False),
        sa.Column("signal_date", sa.Date(), nullable=False),
        sa.Column("execution_date", sa.Date(), nullable=False),
        sa.Column("from_contract", sa.String(length=10), nullable=True),
        sa.Column("to_contract", sa.String(length=10), nullable=False),
        sa.Column("from_price", sa.Numeric(18, 6), nullable=True),
        sa.Column("to_price", sa.Numeric(18, 6), nullable=False),
        sa.Column("quantity_before", sa.Numeric(24, 10), nullable=False),
        sa.Column("quantity_after", sa.Numeric(24, 10), nullable=False),
        sa.Column("notional", sa.Numeric(20, 6), nullable=False),
        sa.Column("transaction_cost", sa.Numeric(20, 6), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("trade_id"),
    )
    op.create_index("ix_index_futures_paper_trade_product", "index_futures_paper_trade", ["product"])
    op.create_index("ix_index_futures_paper_trade_execution_date", "index_futures_paper_trade", ["execution_date"])

    op.create_table(
        "index_futures_market_commentary",
        sa.Column("commentary_id", sa.String(length=36), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("overall_summary", sa.Text(), nullable=False),
        sa.Column("product_commentaries", sa.Text(), nullable=False),
        sa.Column("portfolio_observation", sa.Text(), nullable=False),
        sa.Column("risk_flags", sa.Text(), nullable=False),
        sa.Column("used_llm", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("commentary_id"),
        sa.UniqueConstraint("trade_date", name="uq_index_futures_commentary_trade_date"),
    )
    op.create_index("ix_index_futures_market_commentary_trade_date", "index_futures_market_commentary", ["trade_date"])


def downgrade() -> None:
    op.drop_index("ix_index_futures_market_commentary_trade_date", table_name="index_futures_market_commentary")
    op.drop_table("index_futures_market_commentary")
    op.drop_index("ix_index_futures_paper_trade_execution_date", table_name="index_futures_paper_trade")
    op.drop_index("ix_index_futures_paper_trade_product", table_name="index_futures_paper_trade")
    op.drop_table("index_futures_paper_trade")
    op.drop_index("ix_index_futures_paper_nav_product", table_name="index_futures_paper_nav")
    op.drop_index("ix_index_futures_paper_nav_trade_date", table_name="index_futures_paper_nav")
    op.drop_table("index_futures_paper_nav")
    op.drop_table("index_futures_paper_portfolio")
    op.drop_index("ix_index_futures_basis_snapshot_product", table_name="index_futures_basis_snapshot")
    op.drop_index("ix_index_futures_basis_snapshot_trade_date", table_name="index_futures_basis_snapshot")
    op.drop_table("index_futures_basis_snapshot")
