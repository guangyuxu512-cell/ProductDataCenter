from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


def create_database_engine(settings: Settings) -> Engine:
    if settings.database_url is None:
        raise RuntimeError("BACKEND_DATABASE_URL must be configured before database access")

    return create_engine(str(settings.database_url), pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@lru_cache
def get_database_engine() -> Engine:
    return create_database_engine(get_settings())


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return create_session_factory(get_database_engine())


def get_database_session() -> Iterator[Session]:
    with get_session_factory()() as session:
        yield session
