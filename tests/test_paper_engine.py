"""Tests for the paper trading engine — sizing, pricing, and engine lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_core.config.schema import PaperConfig
from trading_core.db.tables.market_data import CandleRow
from trading_core.db.tables.accounts import AccountMarkToMarketRow, AccountPositionRow, AccountRow
from trading_core.db.tables.signals import SignalRow
from trading_core.paper.engine import PaperEngine
from trading_core.paper.pricing import get_latest_price
from trading_core.paper.sizing import (
    calculate_pnl,
    calculate_position_size,
    calculate_stop_price,
    calculate_take_profit_price,
)

NOW = datetime.now(timezone.utc)

DEFAULT_CONFIG = PaperConfig(
    initial_capital=10000,
    risk_pct=0.02,
    default_stop_loss_pct=0.02,
    default_take_profit_pct=0.04,
    default_timeout_minutes=60,
    kelly_enabled=False,
    slippage_pct={"hyperliquid": 0.0, "polymarket": 0.0},
    fee_pct={"hyperliquid": 0.0, "polymarket": 0.0},
)


# ── Helpers ───────────────────────────────────────────────────


def _seed_candle(session, asset, close, exchange="hyperliquid", minutes_ago=0):
    """Insert a single candle with a given close price."""
    session.add(CandleRow(
        exchange=exchange,
        asset=asset,
        interval="1m",
        open_time=NOW - timedelta(minutes=minutes_ago),
        open=float(close),
        high=float(close) + 100,
        low=float(close) - 100,
        close=float(close),
        volume=1000,
    ))
    session.commit()


def _seed_signal(
    session,
    strategy="funding_rate",
    asset="BTC",
    exchange="hyperliquid",
    direction="LONG",
    entry_price=60000,
    acted_on=False,
    minutes_ago=0,
):
    """Insert a signal row and return it."""
    row = SignalRow(
        ts=NOW - timedelta(minutes=minutes_ago),
        strategy=strategy,
        asset=asset,
        exchange=exchange,
        direction=direction,
        confidence=0.8,
        entry_price=entry_price,
        metadata_={},
        acted_on=acted_on,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _create_account(session, name="default", exchange="hyperliquid",
                    strategy="funding_rate", initial_capital=10000):
    """Create an account and return its ID."""
    return PaperEngine.ensure_account(
        session, name=name, exchange=exchange,
        strategy=strategy, initial_capital=initial_capital,
    )


def _make_engine(session, config=None, account_name="default", exchange="hyperliquid",
                 strategy="funding_rate", initial_capital=10000):
    """Create a PaperEngine with an account."""
    cfg = config or DEFAULT_CONFIG
    aid = _create_account(session, name=account_name, exchange=exchange,
                          strategy=strategy, initial_capital=initial_capital)
    return PaperEngine(cfg, aid, exchange, strategy), aid


# ── TestPositionSizing ────────────────────────────────────────


class TestPositionSizing:
    def test_calculate_position_size(self):
        # 60000 entry, 10000 equity, 2% risk, 2% stop
        # stop_distance = 60000 * 0.02 = 1200
        # risk_amount = 10000 * 0.02 = 200
        # quantity = 200 / 1200 ≈ 0.1667
        qty = calculate_position_size(
            Decimal("60000"), Decimal("10000"), 0.02, 0.02,
        )
        assert float(qty) == pytest.approx(0.1667, rel=1e-2)

    def test_calculate_pnl_long(self):
        pnl = calculate_pnl("LONG", Decimal("60000"), Decimal("61200"), Decimal("0.5"))
        assert pnl == Decimal("600.0")

    def test_calculate_pnl_short(self):
        pnl = calculate_pnl("SHORT", Decimal("60000"), Decimal("58800"), Decimal("0.5"))
        assert pnl == Decimal("600.0")

    def test_calculate_pnl_long_loss(self):
        pnl = calculate_pnl("LONG", Decimal("60000"), Decimal("59000"), Decimal("1"))
        assert pnl == Decimal("-1000")

    def test_calculate_pnl_short_loss(self):
        pnl = calculate_pnl("SHORT", Decimal("60000"), Decimal("61000"), Decimal("1"))
        assert pnl == Decimal("-1000")

    def test_calculate_stop_price_long(self):
        stop = calculate_stop_price("LONG", Decimal("60000"), 0.02)
        assert stop == Decimal("58800")

    def test_calculate_stop_price_short(self):
        stop = calculate_stop_price("SHORT", Decimal("60000"), 0.02)
        assert stop == Decimal("61200")

    def test_calculate_take_profit_price_long(self):
        tp = calculate_take_profit_price("LONG", Decimal("60000"), 0.04)
        assert tp == Decimal("62400")

    def test_calculate_take_profit_price_short(self):
        tp = calculate_take_profit_price("SHORT", Decimal("60000"), 0.04)
        assert tp == Decimal("57600")


# ── TestPricing ───────────────────────────────────────────────


class TestPricing:
    def test_get_latest_price(self, db_session):
        _seed_candle(db_session, "BTC", Decimal("60000"), minutes_ago=5)
        _seed_candle(db_session, "BTC", Decimal("60500"), minutes_ago=0)
        price = get_latest_price(db_session, "BTC")
        assert price == Decimal("60500")

    def test_filters_by_asset(self, db_session):
        _seed_candle(db_session, "BTC", Decimal("60000"))
        _seed_candle(db_session, "ETH", Decimal("3000"))
        price = get_latest_price(db_session, "ETH")
        assert price == Decimal("3000")

    def test_returns_none_if_no_candles(self, db_session):
        price = get_latest_price(db_session, "BTC")
        assert price is None


# ── TestEnsureAccount ───────────────────────────────────────


class TestEnsureAccount:
    def test_creates_if_not_exists(self, db_session):
        aid = PaperEngine.ensure_account(
            db_session, "test_account", "hyperliquid", "funding_rate", 5000,
        )
        row = db_session.get(AccountRow, aid)
        assert row is not None
        assert row.name == "test_account"
        assert float(row.initial_capital) == 5000
        assert row.exchange == "hyperliquid"
        assert row.strategy == "funding_rate"

    def test_returns_existing(self, db_session):
        aid1 = PaperEngine.ensure_account(
            db_session, "default", "hyperliquid", "funding_rate", 10000,
        )
        aid2 = PaperEngine.ensure_account(
            db_session, "default", "hyperliquid", "funding_rate", 10000,
        )
        assert aid1 == aid2


# ── TestConsumeSignals ────────────────────────────────────────


class TestConsumeSignals:
    def test_fetches_unacted_matching_signals(self, db_session):
        engine, _ = _make_engine(db_session, strategy="funding_rate")
        _seed_signal(db_session, exchange="hyperliquid", strategy="funding_rate", acted_on=False)
        _seed_signal(db_session, exchange="hyperliquid", strategy="funding_rate", acted_on=False, asset="ETH")
        signals = engine.consume_signals(db_session)
        assert len(signals) == 2
        assert all(s.exchange == "hyperliquid" for s in signals)

    def test_marks_acted_on(self, db_session):
        engine, _ = _make_engine(db_session, strategy="funding_rate")
        sig = _seed_signal(db_session, exchange="hyperliquid", strategy="funding_rate", acted_on=False)
        engine.consume_signals(db_session)
        db_session.refresh(sig)
        assert sig.acted_on is True

    def test_skips_other_strategy_signals(self, db_session):
        engine, _ = _make_engine(db_session, strategy="funding_rate")
        _seed_signal(db_session, exchange="hyperliquid", strategy="rsi_mean_reversion", acted_on=False)
        _seed_signal(db_session, exchange="hyperliquid", strategy="funding_rate", acted_on=False)
        signals = engine.consume_signals(db_session)
        assert len(signals) == 1
        assert signals[0].strategy == "funding_rate"

    def test_skips_already_acted(self, db_session):
        engine, _ = _make_engine(db_session, strategy="funding_rate")
        _seed_signal(db_session, exchange="hyperliquid", strategy="funding_rate", acted_on=True)
        _seed_signal(db_session, exchange="hyperliquid", strategy="funding_rate", acted_on=False)
        signals = engine.consume_signals(db_session)
        assert len(signals) == 1


# ── TestOpenPosition ──────────────────────────────────────────


class TestOpenPosition:
    def test_creates_position_with_correct_quantity(self, db_session):
        engine, _ = _make_engine(db_session, initial_capital=10000)
        _seed_candle(db_session, "BTC", Decimal("60000"))
        signal = _seed_signal(db_session, asset="BTC", direction="LONG", strategy="funding_rate")
        pos = engine.open_position(db_session, signal, Decimal("10000"))
        assert pos is not None
        assert pos.status == "OPEN"
        assert pos.direction == "LONG"
        # qty = (10000 * 0.02) / (60000 * 0.02) = 200 / 1200 ≈ 0.1667
        assert float(pos.quantity) == pytest.approx(0.1667, rel=1e-2)

    def test_links_signal_id(self, db_session):
        engine, _ = _make_engine(db_session)
        _seed_candle(db_session, "BTC", Decimal("60000"))
        signal = _seed_signal(db_session, strategy="funding_rate")
        pos = engine.open_position(db_session, signal, Decimal("10000"))
        assert pos.signal_id == signal.id

    def test_returns_none_if_no_price(self, db_session):
        engine, _ = _make_engine(db_session)
        signal = _seed_signal(db_session, asset="BTC", strategy="funding_rate")
        # No candles seeded — no price available
        pos = engine.open_position(db_session, signal, Decimal("10000"))
        assert pos is None


# ── TestCheckExits ────────────────────────────────────────────


def _open_position_directly(session, account_id, asset="BTC", direction="LONG",
                            entry_price=60000, quantity=0.1667, minutes_ago=0):
    """Insert a position row directly for exit testing."""
    pos = AccountPositionRow(
        account_id=account_id,
        strategy="funding_rate",
        asset=asset,
        exchange="hyperliquid",
        direction=direction,
        entry_price=entry_price,
        entry_ts=NOW - timedelta(minutes=minutes_ago),
        quantity=quantity,
        status="OPEN",
        metadata_={},
    )
    session.add(pos)
    session.commit()
    session.refresh(pos)
    return pos


class TestCheckExits:
    def test_stop_loss_long(self, db_session):
        engine, aid = _make_engine(db_session)
        _open_position_directly(db_session, aid, direction="LONG", entry_price=60000)
        # Price drops below stop: 60000 * (1 - 0.02) = 58800
        _seed_candle(db_session, "BTC", Decimal("58700"))
        closed = engine.check_exits(db_session, NOW)
        assert len(closed) == 1
        assert closed[0].exit_reason == "stop_loss"

    def test_stop_loss_short(self, db_session):
        engine, aid = _make_engine(db_session)
        _open_position_directly(db_session, aid, direction="SHORT", entry_price=60000)
        # Price rises above stop: 60000 * (1 + 0.02) = 61200
        _seed_candle(db_session, "BTC", Decimal("61300"))
        closed = engine.check_exits(db_session, NOW)
        assert len(closed) == 1
        assert closed[0].exit_reason == "stop_loss"

    def test_take_profit_long(self, db_session):
        engine, aid = _make_engine(db_session)
        _open_position_directly(db_session, aid, direction="LONG", entry_price=60000)
        # Price rises above TP: 60000 * (1 + 0.04) = 62400
        _seed_candle(db_session, "BTC", Decimal("62500"))
        closed = engine.check_exits(db_session, NOW)
        assert len(closed) == 1
        assert closed[0].exit_reason == "take_profit"

    def test_take_profit_short(self, db_session):
        engine, aid = _make_engine(db_session)
        _open_position_directly(db_session, aid, direction="SHORT", entry_price=60000)
        # Price drops below TP: 60000 * (1 - 0.04) = 57600
        _seed_candle(db_session, "BTC", Decimal("57500"))
        closed = engine.check_exits(db_session, NOW)
        assert len(closed) == 1
        assert closed[0].exit_reason == "take_profit"

    def test_timeout(self, db_session):
        engine, aid = _make_engine(db_session)
        # Position opened 61 minutes ago
        _open_position_directly(db_session, aid, direction="LONG", entry_price=60000, minutes_ago=61)
        # Price within bounds (no stop or TP hit)
        _seed_candle(db_session, "BTC", Decimal("60100"))
        closed = engine.check_exits(db_session, NOW)
        assert len(closed) == 1
        assert closed[0].exit_reason == "timeout"

    def test_no_exit_within_bounds(self, db_session):
        engine, aid = _make_engine(db_session)
        _open_position_directly(db_session, aid, direction="LONG", entry_price=60000, minutes_ago=10)
        # Price is between stop (58800) and TP (62400), within timeout
        _seed_candle(db_session, "BTC", Decimal("60500"))
        closed = engine.check_exits(db_session, NOW)
        assert len(closed) == 0


# ── TestClosePosition ─────────────────────────────────────────


class TestClosePosition:
    def test_pnl_long_win(self, db_session):
        engine, aid = _make_engine(db_session)
        pos = _open_position_directly(db_session, aid, direction="LONG", entry_price=60000, quantity=0.5)
        engine.close_position(db_session, pos, Decimal("61000"), "take_profit")
        assert pos.status == "CLOSED"
        # (61000 - 60000) * 0.5 = 500
        assert float(pos.realised_pnl) == pytest.approx(500.0)

    def test_pnl_short_win(self, db_session):
        engine, aid = _make_engine(db_session)
        pos = _open_position_directly(db_session, aid, direction="SHORT", entry_price=60000, quantity=0.5)
        engine.close_position(db_session, pos, Decimal("59000"), "take_profit")
        assert pos.status == "CLOSED"
        # (60000 - 59000) * 0.5 = 500
        assert float(pos.realised_pnl) == pytest.approx(500.0)

    def test_updates_all_fields(self, db_session):
        engine, aid = _make_engine(db_session)
        pos = _open_position_directly(db_session, aid, direction="LONG", entry_price=60000)
        engine.close_position(db_session, pos, Decimal("58000"), "stop_loss")
        assert pos.status == "CLOSED"
        assert pos.exit_reason == "stop_loss"
        assert pos.exit_price is not None
        assert pos.exit_ts is not None
        assert pos.realised_pnl is not None


# ── TestMarkToMarket ──────────────────────────────────────────


class TestMarkToMarket:
    def test_equity_calculation(self, db_session):
        engine, aid = _make_engine(db_session, initial_capital=10000)
        # Close a position with 500 profit
        pos = _open_position_directly(db_session, aid, direction="LONG", entry_price=60000, quantity=0.5)
        engine.close_position(db_session, pos, Decimal("61000"), "take_profit")

        # Open a position with unrealised gain
        _open_position_directly(db_session, aid, direction="LONG", entry_price=50000, quantity=0.1, asset="ETH")
        _seed_candle(db_session, "ETH", Decimal("51000"))

        equity = engine.get_current_equity(db_session)
        # 10000 + 500 (realised) + (51000 - 50000) * 0.1 (unrealised = 100)
        assert float(equity) == pytest.approx(10600.0)

    def test_breakdown_by_strategy(self, db_session):
        engine, aid = _make_engine(db_session, initial_capital=10000)

        # Two open positions with different strategies
        pos1 = AccountPositionRow(
            account_id=aid, strategy="funding_rate", asset="BTC", exchange="hyperliquid",
            direction="LONG", entry_price=60000, entry_ts=NOW, quantity=0.1, status="OPEN", metadata_={},
        )
        pos2 = AccountPositionRow(
            account_id=aid, strategy="rsi_mean_reversion", asset="ETH", exchange="hyperliquid",
            direction="SHORT", entry_price=3000, entry_ts=NOW, quantity=1.0, status="OPEN", metadata_={},
        )
        db_session.add_all([pos1, pos2])
        db_session.commit()

        _seed_candle(db_session, "BTC", Decimal("61000"))
        _seed_candle(db_session, "ETH", Decimal("2900"))

        engine.write_mark_to_market(db_session, NOW)

        mtm = db_session.query(AccountMarkToMarketRow).first()
        assert mtm is not None
        assert mtm.open_positions == 2
        assert "funding_rate" in mtm.breakdown
        assert "rsi_mean_reversion" in mtm.breakdown

    def test_writes_row(self, db_session):
        engine, aid = _make_engine(db_session, initial_capital=10000)
        engine.write_mark_to_market(db_session, NOW)
        rows = db_session.query(AccountMarkToMarketRow).all()
        assert len(rows) == 1
        assert float(rows[0].total_equity) == pytest.approx(10000.0)
        assert rows[0].open_positions == 0
