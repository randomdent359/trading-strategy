"""Tests for the trading_core.metrics module."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from trading_core.db.tables.paper import MarkToMarketRow, PortfolioRow, PositionRow
from trading_core.metrics.cache import MetricsCache
from trading_core.metrics.formulas import (
    StrategyMetrics,
    avg_hold_time_minutes,
    expectancy,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    win_rate,
)
from trading_core.metrics.queries import compute_portfolio_metrics, compute_strategy_metrics

NOW = datetime.now(timezone.utc)


def _seed_portfolio(session: Session, capital: float = 10000) -> PortfolioRow:
    portfolio = PortfolioRow(name="default", initial_capital=capital)
    session.add(portfolio)
    session.commit()
    return portfolio


def _seed_position(
    session: Session,
    portfolio_id: int,
    strategy: str = "test_strat",
    pnl: float = 100.0,
    entry_price: float = 50000.0,
    quantity: float = 0.01,
    minutes_ago_entry: int = 120,
    minutes_ago_exit: int = 60,
) -> PositionRow:
    pos = PositionRow(
        portfolio_id=portfolio_id,
        strategy=strategy,
        asset="BTC",
        exchange="hyperliquid",
        direction="LONG",
        entry_price=entry_price,
        entry_ts=NOW - timedelta(minutes=minutes_ago_entry),
        quantity=quantity,
        exit_price=entry_price + pnl / quantity,
        exit_ts=NOW - timedelta(minutes=minutes_ago_exit),
        exit_reason="take_profit" if pnl > 0 else "stop_loss",
        realised_pnl=pnl,
        status="CLOSED",
    )
    session.add(pos)
    session.commit()
    return pos


def _seed_mtm(
    session: Session,
    portfolio_id: int,
    equity_values: list[float],
) -> list[MarkToMarketRow]:
    rows = []
    for i, eq in enumerate(equity_values):
        row = MarkToMarketRow(
            portfolio_id=portfolio_id,
            ts=NOW - timedelta(hours=len(equity_values) - i),
            total_equity=eq,
            unrealised_pnl=0,
            realised_pnl=eq - equity_values[0],
            open_positions=0,
        )
        session.add(row)
        rows.append(row)
    session.commit()
    return rows


# ═══════════════════════════════════════════════════════════════
# Formula tests (no DB)
# ═══════════════════════════════════════════════════════════════


class TestWinRate:
    def test_basic(self):
        assert win_rate(7, 10) == pytest.approx(70.0)

    def test_zero_total(self):
        assert win_rate(0, 0) == 0.0

    def test_all_wins(self):
        assert win_rate(5, 5) == pytest.approx(100.0)


class TestProfitFactor:
    def test_basic(self):
        assert profit_factor(300.0, 100.0) == pytest.approx(3.0)

    def test_zero_loss(self):
        assert profit_factor(100.0, 0.0) == 0.0

    def test_equal(self):
        assert profit_factor(100.0, 100.0) == pytest.approx(1.0)


class TestExpectancy:
    def test_positive(self):
        # 60% win rate, avg win $200, avg loss $100
        # 0.6*200 - 0.4*100 = 120 - 40 = 80
        assert expectancy(60.0, 200.0, -100.0) == pytest.approx(80.0)

    def test_negative(self):
        # 30% win rate, avg win $100, avg loss $200
        # 0.3*100 - 0.7*200 = 30 - 140 = -110
        assert expectancy(30.0, 100.0, -200.0) == pytest.approx(-110.0)

    def test_zero_wr(self):
        assert expectancy(0.0, 100.0, -50.0) == pytest.approx(-50.0)

    def test_hundred_wr(self):
        assert expectancy(100.0, 100.0, -50.0) == pytest.approx(100.0)


class TestSharpeRatio:
    def test_positive_returns(self):
        returns = [0.01, 0.02, 0.015, 0.01, 0.005]
        result = sharpe_ratio(returns)
        assert result > 0

    def test_single_return(self):
        assert sharpe_ratio([0.01]) == 0.0

    def test_empty(self):
        assert sharpe_ratio([]) == 0.0

    def test_constant_returns(self):
        # All same → std = 0 → ratio = 0
        assert sharpe_ratio([0.01, 0.01, 0.01]) == 0.0

    def test_uses_sample_std(self):
        """Verify ddof=1 (sample std) by checking against manual calc."""
        import numpy as np
        returns = [0.02, -0.01, 0.03, -0.005, 0.01]
        arr = np.array(returns)
        expected = float(np.mean(arr) / np.std(arr, ddof=1) * np.sqrt(252))
        assert sharpe_ratio(returns) == pytest.approx(expected)


class TestSortinoRatio:
    def test_mixed_returns(self):
        returns = [0.02, -0.01, 0.03, -0.005, 0.01]
        result = sortino_ratio(returns)
        assert result > 0

    def test_all_positive(self):
        # No negative returns → downside = all zeros → std with ddof=1 = 0 → 0
        assert sortino_ratio([0.01, 0.02, 0.03]) == 0.0

    def test_single_return(self):
        assert sortino_ratio([0.01]) == 0.0

    def test_empty(self):
        assert sortino_ratio([]) == 0.0

    def test_uses_minimum_zero(self):
        """Verify we use np.minimum(arr, 0) not just filter negatives."""
        import numpy as np
        returns = [0.02, -0.01, 0.03, -0.005, 0.01]
        arr = np.array(returns)
        downside = np.minimum(arr, 0.0)
        expected = float(np.mean(arr) / np.std(downside, ddof=1) * np.sqrt(252))
        assert sortino_ratio(returns) == pytest.approx(expected)


class TestMaxDrawdown:
    def test_basic(self):
        # 100 → 110 → 90 → 105
        # peak: 100, 110, 110, 110
        # dd:   0%, 0%, 18.18%, 4.55%
        result = max_drawdown([100, 110, 90, 105])
        assert result == pytest.approx(18.1818, rel=1e-3)

    def test_monotonic_up(self):
        assert max_drawdown([100, 110, 120, 130]) == pytest.approx(0.0)

    def test_single_value(self):
        assert max_drawdown([100]) == 0.0

    def test_empty(self):
        assert max_drawdown([]) == 0.0

    def test_full_drawdown(self):
        # Goes to zero
        result = max_drawdown([100, 50, 0])
        assert result == pytest.approx(100.0)


class TestAvgHoldTime:
    def test_basic(self):
        # 3600s = 60min, 1800s = 30min → avg = 45min
        assert avg_hold_time_minutes([3600, 1800]) == pytest.approx(45.0)

    def test_empty(self):
        assert avg_hold_time_minutes([]) == 0.0

    def test_single(self):
        assert avg_hold_time_minutes([600]) == pytest.approx(10.0)


# ═══════════════════════════════════════════════════════════════
# Cache tests
# ═══════════════════════════════════════════════════════════════


class TestMetricsCache:
    def test_set_and_get(self):
        cache = MetricsCache(ttl_seconds=10.0)
        cache.set("key", {"value": 42})
        assert cache.get("key") == {"value": 42}

    def test_missing_key(self):
        cache = MetricsCache()
        assert cache.get("nope") is None

    def test_expiry(self):
        cache = MetricsCache(ttl_seconds=0.5)
        cache.set("key", "data")
        assert cache.get("key") == "data"

        # Mock time.monotonic to simulate time passing
        original_time = time.monotonic()
        with patch("trading_core.metrics.cache.time") as mock_time:
            # First call: set time
            mock_time.monotonic.return_value = original_time + 1.0
            assert cache.get("key") is None

    def test_invalidate(self):
        cache = MetricsCache()
        cache.set("key", "data")
        cache.invalidate("key")
        assert cache.get("key") is None

    def test_invalidate_missing(self):
        cache = MetricsCache()
        cache.invalidate("nope")  # Should not raise

    def test_clear(self):
        cache = MetricsCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None


# ═══════════════════════════════════════════════════════════════
# Query integration tests (SQLite)
# ═══════════════════════════════════════════════════════════════


class TestComputeStrategyMetrics:
    def test_no_positions(self, db_session):
        portfolio = _seed_portfolio(db_session)
        m = compute_strategy_metrics(db_session, "nonexistent", portfolio.id)
        assert m.total_trades == 0
        assert m.win_rate == 0.0

    def test_all_wins(self, db_session):
        portfolio = _seed_portfolio(db_session)
        _seed_position(db_session, portfolio.id, pnl=100.0)
        _seed_position(db_session, portfolio.id, pnl=200.0)
        _seed_position(db_session, portfolio.id, pnl=50.0)

        m = compute_strategy_metrics(db_session, "test_strat", portfolio.id)
        assert m.total_trades == 3
        assert m.wins == 3
        assert m.win_rate == pytest.approx(100.0)
        assert m.total_pnl == pytest.approx(350.0)
        assert m.profit_factor == 0.0  # No losses → gross_loss = 0

    def test_mixed(self, db_session):
        portfolio = _seed_portfolio(db_session)
        # 2 wins, 1 loss
        _seed_position(db_session, portfolio.id, pnl=200.0, minutes_ago_entry=180, minutes_ago_exit=120)
        _seed_position(db_session, portfolio.id, pnl=100.0, minutes_ago_entry=120, minutes_ago_exit=60)
        _seed_position(db_session, portfolio.id, pnl=-150.0, minutes_ago_entry=60, minutes_ago_exit=30)

        m = compute_strategy_metrics(db_session, "test_strat", portfolio.id)
        assert m.total_trades == 3
        assert m.wins == 2
        assert m.win_rate == pytest.approx(66.6667, rel=1e-3)
        assert m.total_pnl == pytest.approx(150.0)
        assert m.avg_win == pytest.approx(150.0)  # (200+100)/2
        assert m.avg_loss == pytest.approx(-150.0)
        assert m.profit_factor == pytest.approx(2.0)  # 300/150
        # expectancy: 0.6667*150 - 0.3333*150 = 100 - 50 = 50
        assert m.expectancy == pytest.approx(50.0, rel=1e-2)
        assert m.avg_hold_minutes > 0

    def test_hold_time(self, db_session):
        portfolio = _seed_portfolio(db_session)
        # 60 min hold
        _seed_position(db_session, portfolio.id, pnl=100.0, minutes_ago_entry=120, minutes_ago_exit=60)
        # 30 min hold
        _seed_position(db_session, portfolio.id, pnl=50.0, minutes_ago_entry=60, minutes_ago_exit=30)

        m = compute_strategy_metrics(db_session, "test_strat", portfolio.id)
        assert m.avg_hold_minutes == pytest.approx(45.0)


class TestComputePortfolioMetrics:
    def test_with_mtm(self, db_session):
        portfolio = _seed_portfolio(db_session, capital=10000)
        _seed_position(db_session, portfolio.id, pnl=100.0)
        _seed_position(db_session, portfolio.id, pnl=-50.0, minutes_ago_entry=60, minutes_ago_exit=30)

        # Seed equity curve: 10000 → 10100 → 10050
        _seed_mtm(db_session, portfolio.id, [10000, 10100, 10050])

        m = compute_portfolio_metrics(db_session, portfolio.id)
        assert m.total_trades == 2
        assert m.wins == 1
        assert m.total_pnl == pytest.approx(50.0)
        # Sharpe/Sortino computed from MTM returns, not per-trade
        # Returns: 10100/10000-1 = 0.01, 10050/10100-1 ≈ -0.00495
        assert m.sharpe_ratio != 0.0
        assert m.max_drawdown > 0

    def test_no_positions(self, db_session):
        portfolio = _seed_portfolio(db_session)
        m = compute_portfolio_metrics(db_session, portfolio.id)
        assert m.total_trades == 0
        assert m.sharpe_ratio == 0.0
