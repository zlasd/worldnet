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
