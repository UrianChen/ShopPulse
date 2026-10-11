from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings


@lru_cache
def engine():
    return create_engine(
        settings().database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"connect_timeout": 5},
        hide_parameters=True,
    )


def db_session():
    with Session(engine(), expire_on_commit=False) as session:
        yield session
