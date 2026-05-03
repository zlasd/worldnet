from app.db.session import get_engine_kwargs


def test_sqlite_engine_kwargs_include_check_same_thread():
    kwargs = get_engine_kwargs("sqlite:///./worldnet.db")

    assert kwargs["connect_args"] == {"check_same_thread": False}
    assert kwargs["pool_pre_ping"] is True


def test_postgres_engine_kwargs_skip_sqlite_connect_args():
    kwargs = get_engine_kwargs("postgresql+psycopg://worldnet:secret@postgres/worldnet")

    assert "connect_args" not in kwargs
    assert kwargs["pool_pre_ping"] is True
