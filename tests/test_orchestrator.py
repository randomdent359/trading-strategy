"""Tests for orchestrator — persistence and snapshot builder."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_core.db.tables.market_data import CandleRow, FundingSnapshotRow, PolymarketMarketRow
from trading_core.db.tables.signals import SignalRow
from trading_core.models import Signal
from trading_core.orchestrator.persistence import persist_signal
from trading_core.orchestrator.snapshot import build_snapshot

NOW = datetime.now(timezone.utc)


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


# ── Snapshot Builder ────────────────────────────────────────────


def _seed_candles(session, asset, n=30):
    """Insert N candle rows for an asset."""
    for i in range(n):
        session.add(CandleRow(
            exchange="hyperliquid",
            asset=asset,
            interval="1m",
            open_time=NOW - timedelta(minutes=n - i),
            open=100 + i,
            high=101 + i,
            low=99 + i,
            close=100.5 + i,
            volume=1000 + i * 10,
        ))
    session.commit()


def _seed_funding(session, asset, n=10):
    """Insert N funding snapshot rows."""
    for i in range(n):
        session.add(FundingSnapshotRow(
            exchange="hyperliquid",
            asset=asset,
            ts=NOW - timedelta(hours=n - i),
            funding_rate=0.0001 * (i + 1),
            open_interest=50000 + i * 1000,
            mark_price=60000 + i * 100,
        ))
    session.commit()


def _seed_polymarket(session, asset, n=5, end_date=None):
    """Insert N Polymarket observation rows."""
    for i in range(n):
        session.add(PolymarketMarketRow(
            market_id=f"mkt-{asset}-{i}",
            market_title=f"Will {asset} go up?",
            asset=asset,
            ts=NOW - timedelta(hours=n - i),
            yes_price=0.55 + i * 0.05,
            no_price=0.45 - i * 0.05,
            volume_24h=10000,
            liquidity=50000,
            end_date=end_date,
        ))
    session.commit()


class TestBuildSnapshot:
    def test_empty_db_returns_empty_snapshot(self, db_session):
        snap = build_snapshot(db_session, "BTC")
        assert snap.asset == "BTC"
        assert snap.candles == []
        assert snap.funding == []
        assert snap.polymarket == []

    def test_candles_populated(self, db_session):
        _seed_candles(db_session, "BTC", n=30)
        snap = build_snapshot(db_session, "BTC", candle_limit=20)
        assert len(snap.candles) == 20
        # Should be ordered oldest first
        assert snap.candles[0].open_time < snap.candles[-1].open_time

    def test_funding_populated(self, db_session):
        _seed_funding(db_session, "ETH", n=10)
        snap = build_snapshot(db_session, "ETH", funding_days=7)
        assert len(snap.funding) == 10
        assert snap.funding[0].ts < snap.funding[-1].ts

    def test_polymarket_populated(self, db_session):
        _seed_polymarket(db_session, "SOL", n=5)
        snap = build_snapshot(db_session, "SOL", polymarket_limit=3)
        assert len(snap.polymarket) == 3
        # Should be ordered oldest first
        assert snap.polymarket[0].ts < snap.polymarket[-1].ts

    def test_asset_filtering(self, db_session):
        _seed_candles(db_session, "BTC", n=10)
        _seed_candles(db_session, "ETH", n=5)
        snap = build_snapshot(db_session, "BTC")
        # Should only contain BTC candles
        assert all(c.asset == "BTC" for c in snap.candles)
        assert len(snap.candles) == 10

    def test_funding_days_cutoff(self, db_session):
        # Insert funding data that's older than the cutoff
        for i in range(5):
            db_session.add(FundingSnapshotRow(
                exchange="hyperliquid",
                asset="BTC",
                ts=NOW - timedelta(days=10 + i),
                funding_rate=0.001,
                open_interest=50000,
                mark_price=60000,
            ))
        # Insert recent data
        _seed_funding(db_session, "BTC", n=3)
        snap = build_snapshot(db_session, "BTC", funding_days=7)
        # Only recent data should be included
        assert len(snap.funding) == 3

    def test_polymarket_end_date_passed_through(self, db_session):
        future = NOW + timedelta(days=30)
        _seed_polymarket(db_session, "BTC", n=2, end_date=future)
        snap = build_snapshot(db_session, "BTC")
        assert len(snap.polymarket) == 2
        for pm in snap.polymarket:
            assert pm.end_date is not None
            # SQLite strips tzinfo, so compare the naive datetime parts
            assert pm.end_date.replace(tzinfo=None) == future.replace(tzinfo=None)

    def test_polymarket_null_end_date(self, db_session):
        _seed_polymarket(db_session, "ETH", n=2, end_date=None)
        snap = build_snapshot(db_session, "ETH")
        assert len(snap.polymarket) == 2
        for pm in snap.polymarket:
            assert pm.end_date is None

    def test_full_snapshot(self, db_session):
        _seed_candles(db_session, "BTC", n=30)
        _seed_funding(db_session, "BTC", n=10)
        _seed_polymarket(db_session, "BTC", n=5)
        snap = build_snapshot(db_session, "BTC")
        assert len(snap.candles) == 30
        assert len(snap.funding) == 10
        assert len(snap.polymarket) == 5
        assert snap.asset == "BTC"
        assert snap.ts is not None
