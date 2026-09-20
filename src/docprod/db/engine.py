from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


def sqlalchemy_database_url(database_url: str) -> str:
    """Accept Neon/Railway postgres:// URLs for SQLAlchemy+psycopg."""
    raw = database_url.strip()
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    if raw.startswith("postgresql://") and "+psycopg" not in raw.split("://", 1)[0]:
        raw = "postgresql+psycopg://" + raw[len("postgresql://") :]
    return raw


def uses_serverless_pool(database_url: str) -> bool:
    lowered = database_url.lower()
    return "-pooler." in lowered or "pgbouncer=true" in lowered


def make_engine(
    database_url: str,
    *,
    echo: bool = False,
    serverless: bool | None = None,
) -> Engine:
    if not database_url:
        raise ValueError("DATABASE_URL is required for postgres persistence")
    url = sqlalchemy_database_url(database_url)
    kwargs: dict = {"echo": echo, "pool_pre_ping": True, "future": True}
    if serverless is None:
        serverless = uses_serverless_pool(url)
    if serverless:
        kwargs["poolclass"] = NullPool
    return create_engine(url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)


def ping_engine(engine: Engine) -> bool:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
