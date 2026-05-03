from contextlib import contextmanager
from typing import Any, Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def get_engine_kwargs(database_url: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "echo": settings.db_echo,
        "pool_pre_ping": True,
    }
    if make_url(database_url).get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
    return kwargs


engine = create_engine(
    settings.database_url,
    **get_engine_kwargs(settings.database_url),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
