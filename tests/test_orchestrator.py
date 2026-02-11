"""Tests for orchestrator — persistence and snapshot builder."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import BigInteger, Integer, JSON, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from trading_core.db.base import Base
from trading_core.db.tables.market_data import CandleRow, FundingSnapshotRow, PolymarketMarketRow
from trading_core.db.tables.signals import SignalRow
from trading_core.models import Signal
from trading_core.orchestrator.persistence import persist_signal

NOW = datetime.now(timezone.utc)


@pytest.fixture
def db_session():
    """In-memory SQLite session with all schemas/tables created."""
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


# ── Signal Persistence ──────────────────────────────────────────


class TestPersistSignal:
    def test_inserts_and_returns_id(self, db_session):
        signal = Signal(
            strategy="funding_rate",
            asset="BTC",
            exchange="hyperliquid",
            direction="SHORT",
            confidence=0.8,
            entry_price=Decimal("60000"),
            metadata={"funding_rate": "0.002"},
            ts=NOW,
        )
        row_id = persist_signal(db_session, signal)
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_values_persisted_correctly(self, db_session):
        signal = Signal(
            strategy="contrarian_pure",
            asset="ETH",
            exchange="polymarket",
            direction="LONG",
            confidence=0.65,
            entry_price=Decimal("0.25"),
            metadata={"market_id": "test-123", "yes_price": "0.25"},
            ts=NOW,
        )
        row_id = persist_signal(db_session, signal)
        row = db_session.get(SignalRow, row_id)
        assert row is not None
        assert row.strategy == "contrarian_pure"
        assert row.asset == "ETH"
        assert row.exchange == "polymarket"
        assert row.direction == "LONG"
        assert float(row.confidence) == pytest.approx(0.65)
        assert row.acted_on is False

    def test_metadata_stored_as_dict(self, db_session):
        signal = Signal(
            strategy="rsi_mean_reversion",
            asset="SOL",
            exchange="hyperliquid",
            direction="SHORT",
            confidence=0.9,
            entry_price=Decimal("150"),
            metadata={"rsi": "82.5", "period": 14},
            ts=NOW,
        )
        row_id = persist_signal(db_session, signal)
        row = db_session.get(SignalRow, row_id)
        assert row.metadata_ is not None
        assert row.metadata_["rsi"] == "82.5"

    def test_multiple_signals_get_unique_ids(self, db_session):
        ids = []
        for i in range(3):
            signal = Signal(
                strategy="funding_arb",
                asset="BTC",
                exchange="hyperliquid",
                direction="SHORT",
                confidence=0.5 + i * 0.1,
                entry_price=Decimal("60000"),
                ts=NOW,
            )
            ids.append(persist_signal(db_session, signal))
        assert len(set(ids)) == 3
