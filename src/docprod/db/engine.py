from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def sqlalchemy_database_url(database_url: str) -> str:
    """Accept Railway postgres:// / postgresql:// URLs for SQLAlchemy+psycopg."""
    raw = database_url.strip()
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://") and "+psycopg" not in raw.split("://", 1)[0]:
        raw = "postgresql+psycopg://" + raw[len("postgresql://") :]
    return raw


def make_engine(database_url: str, *, echo: bool = False) -> Engine:
    if not database_url:
        raise ValueError("DATABASE_URL is required for postgres persistence")
    return create_engine(
        sqlalchemy_database_url(database_url),
        echo=echo,
        pool_pre_ping=True,
        future=True,
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)


def ping_engine(engine: Engine) -> bool:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
