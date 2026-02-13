"""Test paper engine integration with slippage and fees."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_core.config.schema import PaperConfig
from trading_core.db.tables.market_data import CandleRow
from trading_core.db.tables.accounts import AccountMarkToMarketRow, AccountPositionRow
from trading_core.db.tables.signals import SignalRow
from trading_core.paper.engine import PaperEngine

NOW = datetime.now(timezone.utc)


@pytest.fixture
def paper_config():
    """Paper config with slippage and fees configured."""
    return PaperConfig(
        initial_capital=10000,
        risk_pct=0.02,
        default_stop_loss_pct=0.02,
        default_take_profit_pct=0.04,
        default_timeout_minutes=60,
        kelly_enabled=False,
        slippage_pct={
            "hyperliquid": 0.001,  # 0.1%
            "polymarket": 0.005,   # 0.5%
        },
        fee_pct={
            "hyperliquid": 0.0005,  # 0.05%
            "polymarket": 0.002,    # 0.2%
        },
    )


@pytest.fixture
def setup_account(db_session):
    """Create an account and return (engine, account_id)."""
    def _setup(config, exchange="hyperliquid", strategy="test_strategy"):
        aid = PaperEngine.ensure_account(
            db_session, f"test_{exchange}_{strategy}", exchange, strategy, 10000,
        )
        engine = PaperEngine(config, aid, exchange, strategy)
        return engine, aid
    return _setup


@pytest.fixture
def add_candle(db_session):
    """Helper to add a candle with auto-incrementing timestamp."""
    counter = {"n": 0}

    def _add(asset="BTC", exchange="hyperliquid", close_price=100.0):
        counter["n"] += 1
        candle = CandleRow(
            exchange=exchange,
            asset=asset,
            interval="1m",
            open_time=NOW - timedelta(minutes=100 - counter["n"]),
            open=close_price,
            high=close_price,
            low=close_price,
            close=close_price,
            volume=1000,
        )
        db_session.add(candle)
        db_session.commit()
        return candle
    return _add


@pytest.fixture
def add_signal(db_session):
    """Helper to add a signal."""
    def _add(
        strategy="test_strategy",
        asset="BTC",
        exchange="hyperliquid",
        direction="LONG",
        confidence=0.7,
        entry_price=100.0,
    ):
        signal = SignalRow(
            ts=NOW,
            strategy=strategy,
            asset=asset,
            exchange=exchange,
            direction=direction,
            confidence=confidence,
            entry_price=entry_price,
            metadata_={},
            acted_on=False,
        )
        db_session.add(signal)
        db_session.commit()
        db_session.refresh(signal)
        return signal
    return _add


class TestSlippageFeeIntegration:
    """Test that slippage and fees are correctly applied in the paper engine."""

    def test_position_entry_with_slippage(self, db_session, paper_config, setup_account, add_candle, add_signal):
        """Test that slippage is applied when opening a position."""
        engine, aid = setup_account(paper_config)

        # Add market data
        add_candle(asset="BTC", exchange="hyperliquid", close_price=100.0)

        # Add a LONG signal
        signal = add_signal(direction="LONG", entry_price=100.0)

        # Open position
        position = engine.open_position(db_session, signal, Decimal("10000"))

        assert position is not None
        # With 0.1% slippage on LONG entry, we pay more
        expected_entry = 100.0 * 1.001  # 100.10
        assert float(position.entry_price) == pytest.approx(expected_entry, rel=1e-6)

        # Check metadata
        assert position.metadata_ is not None
        assert position.metadata_["raw_price"] == 100.0
        assert position.metadata_["slippage_pct"] == 0.001

    def test_position_exit_with_slippage_and_fees(self, db_session, paper_config, setup_account, add_candle, add_signal):
        """Test that slippage and fees are applied when closing a position."""
        engine, aid = setup_account(paper_config)

        # Add initial market data
        add_candle(asset="BTC", exchange="hyperliquid", close_price=100.0)

        # Add and open a LONG position
        signal = add_signal(direction="LONG", entry_price=100.0)
        position = engine.open_position(db_session, signal, Decimal("10000"))

        # Price moves up to 110 (profitable trade)
        add_candle(asset="BTC", exchange="hyperliquid", close_price=110.0)

        # Close position
        engine.close_position(db_session, position, Decimal("110.0"), "take_profit")

        # Verify exit price has slippage applied
        # LONG exit with 0.1% slippage: receive less
        expected_exit = 110.0 * 0.999  # 109.89
        assert float(position.exit_price) == pytest.approx(expected_exit, rel=1e-6)

        # Verify fees were deducted from P&L
        assert position.realised_pnl is not None
        assert position.metadata_["fees"] > 0
        assert position.metadata_["gross_pnl"] > position.realised_pnl

    def test_short_position_slippage(self, db_session, paper_config, setup_account, add_candle, add_signal):
        """Test slippage for SHORT positions."""
        engine, aid = setup_account(paper_config)

        # Add market data
        add_candle(asset="ETH", exchange="hyperliquid", close_price=2000.0)

        # Add a SHORT signal
        signal = add_signal(asset="ETH", direction="SHORT", entry_price=2000.0)

        # Open position
        position = engine.open_position(db_session, signal, Decimal("10000"))

        assert position is not None
        # With 0.1% slippage on SHORT entry, we receive less
        expected_entry = 2000.0 * 0.999  # 1998.00
        assert float(position.entry_price) == pytest.approx(expected_entry, rel=1e-6)

        # Price drops to 1900 (profitable short)
        add_candle(asset="ETH", exchange="hyperliquid", close_price=1900.0)

        # Close position
        engine.close_position(db_session, position, Decimal("1900.0"), "take_profit")

        # SHORT exit with 0.1% slippage: pay more
        expected_exit = 1900.0 * 1.001  # 1901.90
        assert float(position.exit_price) == pytest.approx(expected_exit, rel=1e-6)

        # Should be profitable even after slippage and fees
        assert position.realised_pnl > 0

    def test_polymarket_higher_slippage(self, db_session, paper_config, setup_account, add_candle, add_signal):
        """Test that Polymarket positions use higher slippage."""
        engine, aid = setup_account(paper_config, exchange="polymarket", strategy="test_strategy")

        # Add market data for Polymarket
        add_candle(asset="BTC", exchange="polymarket", close_price=50000.0)

        # Add a signal for Polymarket
        signal = add_signal(exchange="polymarket", entry_price=50000.0)

        # Open position
        position = engine.open_position(db_session, signal, Decimal("10000"))

        assert position is not None
        # With 0.5% slippage on LONG entry
        expected_entry = 50000.0 * 1.005  # 50250.00
        assert float(position.entry_price) == pytest.approx(expected_entry, rel=1e-6)

        # Verify correct slippage percentage in metadata
        assert position.metadata_["slippage_pct"] == 0.005

    def test_unrealized_pnl_includes_slippage_fees(self, db_session, paper_config, setup_account, add_candle, add_signal):
        """Test that unrealized P&L calculation includes slippage and fees."""
        engine, aid = setup_account(paper_config)

        # Add initial market data
        add_candle(asset="BTC", exchange="hyperliquid", close_price=100.0)

        # Open a position
        signal = add_signal(direction="LONG", entry_price=100.0)
        position = engine.open_position(db_session, signal, Decimal("10000"))

        # Update price
        add_candle(asset="BTC", exchange="hyperliquid", close_price=105.0)

        # Calculate current equity (includes unrealized P&L)
        equity = engine.get_current_equity(db_session)

        # Equity should be less than simple calculation due to slippage/fees
        # Simple: 10000 + (105 - 100.1) * quantity
        # Actual: considers exit slippage and round-trip fees
        assert equity < Decimal("10000") + (Decimal("105") - Decimal("100.1")) * Decimal(str(position.quantity))

    def test_mark_to_market_with_costs(self, db_session, paper_config, setup_account, add_candle, add_signal):
        """Test that mark-to-market snapshots include slippage and fees."""
        engine, aid = setup_account(paper_config)

        # Open multiple positions
        positions = []
        for i, asset in enumerate(["BTC", "ETH", "SOL"]):
            add_candle(asset=asset, exchange="hyperliquid", close_price=100.0 * (i + 1))
            signal = add_signal(asset=asset, entry_price=100.0 * (i + 1))
            pos = engine.open_position(db_session, signal, Decimal("10000"))
            positions.append(pos)

        # Update prices (all up 5%)
        for i, asset in enumerate(["BTC", "ETH", "SOL"]):
            add_candle(asset=asset, exchange="hyperliquid", close_price=105.0 * (i + 1))

        # Write MTM snapshot
        engine.write_mark_to_market(db_session, NOW)

        # Verify MTM was written
        mtm = db_session.query(AccountMarkToMarketRow).first()
        assert mtm is not None
        assert mtm.open_positions == 3
        assert mtm.unrealised_pnl > 0  # Profitable but reduced by costs

        # Breakdown should show per-strategy unrealized P&L
        assert "test_strategy" in mtm.breakdown
        assert mtm.breakdown["test_strategy"]["open_positions"] == 3
        assert mtm.breakdown["test_strategy"]["unrealised_pnl"] > 0

    def test_stop_loss_with_slippage(self, db_session, paper_config, setup_account, add_candle, add_signal):
        """Test that stop loss triggers consider slippage."""
        engine, aid = setup_account(paper_config)

        # Open a LONG position at 100
        add_candle(asset="BTC", exchange="hyperliquid", close_price=100.0)
        signal = add_signal(direction="LONG", entry_price=100.0)
        position = engine.open_position(db_session, signal, Decimal("10000"))

        # Price drops to exactly 2% below entry (stop loss trigger)
        # Note: stop loss is calculated on actual entry price (with slippage)
        stop_price = float(position.entry_price) * 0.98
        add_candle(asset="BTC", exchange="hyperliquid", close_price=stop_price)

        # Check exits
        closed = engine.check_exits(db_session, NOW)

        assert len(closed) == 1
        assert closed[0].exit_reason == "stop_loss"
        assert closed[0].realised_pnl < 0  # Loss due to stop + slippage + fees

    def test_no_slippage_fees_when_disabled(self, db_session, setup_account, add_candle, add_signal):
        """Test that setting slippage/fees to 0 disables them."""
        # Create config with no slippage or fees
        config = PaperConfig(
            kelly_enabled=False,
            slippage_pct={"hyperliquid": 0.0},
            fee_pct={"hyperliquid": 0.0},
        )
        engine, aid = setup_account(config)

        # Open and close a position
        add_candle(asset="BTC", exchange="hyperliquid", close_price=100.0)
        signal = add_signal(direction="LONG", entry_price=100.0)
        position = engine.open_position(db_session, signal, Decimal("10000"))

        assert float(position.entry_price) == 100.0  # No slippage

        add_candle(asset="BTC", exchange="hyperliquid", close_price=110.0)
        engine.close_position(db_session, position, Decimal("110.0"), "take_profit")

        assert float(position.exit_price) == 110.0  # No slippage
        assert position.metadata_["fees"] == 0.0  # No fees
        assert float(position.realised_pnl) == pytest.approx(position.metadata_["gross_pnl"])  # Net = Gross
