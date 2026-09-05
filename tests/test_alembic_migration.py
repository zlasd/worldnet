from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_head_creates_initial_schema(tmp_path):
    db_path = tmp_path / "worldnet.db"
    config = Config(str(Path("alembic.ini").resolve()))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    assert {
        "digest_item",
        "digest_log",
        "index_futures_basis_snapshot",
        "index_futures_market_commentary",
        "index_futures_paper_nav",
        "index_futures_paper_portfolio",
        "index_futures_paper_trade",
        "notification_log",
        "normalized_event",
        "source_document",
    }.issubset(set(inspector.get_table_names()))

    notification_columns = {column["name"] for column in inspector.get_columns("notification_log")}
    assert {
        "attempt_count",
        "last_attempt_at",
        "next_retry_at",
        "last_error",
        "finalized_at",
        "updated_at",
    }.issubset(notification_columns)

    watchlist_item_columns = {column["name"] for column in inspector.get_columns("watchlist_item")}
    assert {"is_active", "updated_at"}.issubset(watchlist_item_columns)

    basis_columns = {
        column["name"] for column in inspector.get_columns("index_futures_basis_snapshot")
    }
    assert "spot_pe" in basis_columns


def test_digest_source_upgrade_preserves_existing_history(tmp_path):
    from sqlalchemy import text

    db_path = tmp_path / "existing.db"
    config = Config(str(Path("alembic.ini").resolve()))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "0004_index_futures_pe")
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO digest_log (digest_id, digest_type, window_start, window_end, outlet_id,
                channel, title, status, attempt_count, created_at, updated_at)
            VALUES ('existing', 'important_daily', '2026-08-31', '2026-09-01', 'none',
                'none', 'Existing history', 'skipped', 0, '2026-09-01', '2026-09-01')
        """)
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT title, source_instance FROM digest_log")).one()
    assert row == ("Existing history", None)
    engine.dispose()
