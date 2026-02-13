"""Shared test fixtures."""

import pytest
from sqlalchemy import BigInteger, Integer, JSON, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from trading_core.db.base import Base


@pytest.fixture
def db_session():
    """In-memory SQLite session with all schemas/tables created.

    Patches JSONB→JSON and BigInteger→Integer for SQLite compatibility.
    """
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    # SQLite doesn't support schemas, JSONB, or BigInteger autoincrement
    for table in Base.metadata.tables.values():
        table.schema = None
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()
            if isinstance(col.type, BigInteger):
                col.type = Integer()

    Base.metadata.create_all(engine)

    session = Session(engine)
    yield session
    session.close()
    engine.dispose()
