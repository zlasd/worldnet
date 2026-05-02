import app.models  # noqa: F401 - registers all models with Base.metadata
from app.db.base import Base
from app.db.session import engine


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
