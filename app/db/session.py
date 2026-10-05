from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


def create_database_engine(settings: Settings) -> Engine:
    if settings.database_url is None:
        raise ValueError("Set DATABASE_URL before using the database")
    try:
        url = make_url(settings.database_url.get_secret_value())
    except ArgumentError:
        raise ValueError("DATABASE_URL must be a valid PostgreSQL URL") from None
    if url.drivername != "postgresql+psycopg":
        raise ValueError("DATABASE_URL must use postgresql+psycopg")
    return create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"options": "-c timezone=UTC", "connect_timeout": 5},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    # Lazily initialize: the process health endpoint does not require a database.
    factory = get_session_factory()
    with factory() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        # Closing also rolls back uncommitted work. Services explicitly commit writes.


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return create_session_factory(create_database_engine(get_settings()))
