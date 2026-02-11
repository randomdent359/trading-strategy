"""Tests for Pydantic domain models."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_core.models import (
    FundingSnapshot,
    MarkToMarket,
    MarketSnapshot,
    OHLCV,
    PolymarketMarket,
    Portfolio,
    Position,
    Signal,
)

NOW = datetime.now(timezone.utc)


class TestSignal:
    def test_valid_signal(self):
        s = Signal(
            strategy="contrarian_pure",
            asset="BTC",
            exchange="hyperliquid",
            direction="LONG",
            confidence=0.85,
            entry_price=Decimal("60000.50"),
            ts=NOW,
        )
        assert s.direction == "LONG"
        assert s.confidence == 0.85
        assert s.metadata == {}

    def test_signal_with_metadata(self):
        s = Signal(
            strategy="funding_rate",
            asset="ETH",
            exchange="hyperliquid",
            direction="SHORT",
            confidence=0.72,
            entry_price=Decimal("3200"),
            metadata={"funding_rate": 0.0015},
            ts=NOW,
        )
        assert s.metadata["funding_rate"] == 0.0015

    def test_invalid_direction(self):
        with pytest.raises(ValidationError):
            Signal(
                strategy="test",
                asset="BTC",
                exchange="hyperliquid",
                direction="UP",
                confidence=0.5,
                entry_price=Decimal("100"),
                ts=NOW,
            )

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            Signal(
                strategy="test",
                asset="BTC",
                exchange="hyperliquid",
                direction="LONG",
                confidence=1.5,
                entry_price=Decimal("100"),
                ts=NOW,
            )
        with pytest.raises(ValidationError):
            Signal(
                strategy="test",
                asset="BTC",
                exchange="hyperliquid",
                direction="LONG",
                confidence=-0.1,
                entry_price=Decimal("100"),
                ts=NOW,
            )


class TestOHLCV:
    def test_valid_candle(self):
        c = OHLCV(
            exchange="hyperliquid",
            asset="BTC",
            interval="1m",
            open_time=NOW,
            open=Decimal("60000"),
            high=Decimal("60100"),
            low=Decimal("59900"),
            close=Decimal("60050"),
            volume=Decimal("123.45"),
        )
        assert c.asset == "BTC"
        assert c.interval == "1m"


class TestFundingSnapshot:
    def test_with_optional_fields(self):
        f = FundingSnapshot(
            exchange="hyperliquid",
            asset="ETH",
            ts=NOW,
            funding_rate=Decimal("0.0012"),
            open_interest=Decimal("500000000"),
            mark_price=Decimal("3200.50"),
        )
        assert f.open_interest == Decimal("500000000")

    def test_without_optional_fields(self):
        f = FundingSnapshot(
            exchange="hyperliquid",
            asset="SOL",
            ts=NOW,
            funding_rate=Decimal("-0.0005"),
        )
        assert f.open_interest is None
        assert f.mark_price is None


class TestPolymarketMarket:
    def test_valid_market(self):
        m = PolymarketMarket(
            market_id="0xabc123",
            market_title="BTC above 100k by March?",
            asset="BTC",
            ts=NOW,
            yes_price=Decimal("0.72"),
            no_price=Decimal("0.28"),
        )
        assert m.market_id == "0xabc123"


class TestMarketSnapshot:
    def test_empty_snapshot(self):
        snap = MarketSnapshot(asset="BTC", ts=NOW)
        assert snap.candles == []
        assert snap.funding == []
        assert snap.polymarket == []

    def test_snapshot_with_data(self):
        candle = OHLCV(
            exchange="hyperliquid",
            asset="BTC",
            interval="1m",
            open_time=NOW,
            open=Decimal("60000"),
            high=Decimal("60100"),
            low=Decimal("59900"),
            close=Decimal("60050"),
            volume=Decimal("100"),
        )
        snap = MarketSnapshot(asset="BTC", ts=NOW, candles=[candle])
        assert len(snap.candles) == 1


class TestPortfolio:
    def test_defaults(self):
        p = Portfolio(name="default")
        assert p.initial_capital == Decimal("10000")
        assert p.created_at is None


class TestPosition:
    def test_open_position(self):
        pos = Position(
            portfolio_id=1,
            strategy="contrarian_pure",
            asset="BTC",
            exchange="hyperliquid",
            direction="LONG",
            entry_price=Decimal("60000"),
            entry_ts=NOW,
            quantity=Decimal("0.01"),
        )
        assert pos.status == "OPEN"
        assert pos.exit_price is None

    def test_closed_position(self):
        pos = Position(
            portfolio_id=1,
            strategy="funding_rate",
            asset="ETH",
            exchange="hyperliquid",
            direction="SHORT",
            entry_price=Decimal("3200"),
            entry_ts=NOW,
            quantity=Decimal("1.0"),
            exit_price=Decimal("3150"),
            exit_ts=NOW,
            exit_reason="take_profit",
            realised_pnl=Decimal("50"),
            status="CLOSED",
        )
        assert pos.status == "CLOSED"
        assert pos.realised_pnl == Decimal("50")


class TestMarkToMarket:
    def test_valid_snapshot(self):
        m = MarkToMarket(
            portfolio_id=1,
            ts=NOW,
            total_equity=Decimal("10500"),
            unrealised_pnl=Decimal("300"),
            realised_pnl=Decimal("200"),
            open_positions=3,
            breakdown={"contrarian_pure": {"pnl": 150}},
        )
        assert m.open_positions == 3
        assert m.breakdown["contrarian_pure"]["pnl"] == 150
