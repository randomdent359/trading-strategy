"""Database engine and session management."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_engine(url: str, **kwargs) -> Engine:
    """Create the global engine and session factory."""
    global _engine, _SessionLocal
    _engine = create_engine(url, **kwargs)
    _SessionLocal = sessionmaker(bind=_engine)
    return _engine


def get_engine() -> Engine:
    """Return the global engine (must call init_engine first)."""
    if _engine is None:
        raise RuntimeError("Database engine not initialised — call init_engine() first")
    return _engine


def get_session() -> Generator[Session, None, None]:
    """Yield a session, closing it when done."""
    if _SessionLocal is None:
        raise RuntimeError("Database engine not initialised — call init_engine() first")
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
