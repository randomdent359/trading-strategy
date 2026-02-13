"""Tests for account and portfolio management."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_core.config.schema import PaperConfig
from trading_core.db.tables.accounts import (
    AccountMarkToMarketRow,
    AccountPositionRow,
    AccountRow,
    PortfolioGroupRow,
    PortfolioMemberRow,
)
from trading_core.db.tables.signals import SignalRow
from trading_core.db.tables.market_data import CandleRow
from trading_core.paper.engine import PaperEngine

NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

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


def _seed_signal(session, strategy="funding_rate", asset="BTC", exchange="hyperliquid",
                 direction="LONG", entry_price=60000, confidence=0.8, acted_on=False):
    row = SignalRow(
        ts=NOW,
        strategy=strategy,
        asset=asset,
        exchange=exchange,
        direction=direction,
        confidence=confidence,
        entry_price=entry_price,
        metadata_={},
        acted_on=acted_on,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _make_engine(session, exchange="hyperliquid", strategy="funding_rate",
                 name=None, initial_capital=10000, config=None):
    cfg = config or DEFAULT_CONFIG
    account_name = name or f"{strategy}_{exchange}"
    aid = PaperEngine.ensure_account(
        session, name=account_name, exchange=exchange,
        strategy=strategy, initial_capital=initial_capital,
    )
    return PaperEngine(cfg, aid, exchange, strategy), aid


# ── Account CRUD ──────────────────────────────────────────────


class TestAccountCRUD:
    def test_ensure_account_creates_new(self, db_session):
        aid = PaperEngine.ensure_account(
            db_session, "test_acct", "hyperliquid", "funding_rate", 5000,
        )
        row = db_session.get(AccountRow, aid)
        assert row is not None
        assert row.name == "test_acct"
        assert row.exchange == "hyperliquid"
        assert row.strategy == "funding_rate"
        assert float(row.initial_capital) == 5000

    def test_ensure_account_idempotent(self, db_session):
        aid1 = PaperEngine.ensure_account(db_session, "a", "hl", "s", 1000)
        aid2 = PaperEngine.ensure_account(db_session, "a", "hl", "s", 1000)
        assert aid1 == aid2

    def test_unique_name_constraint(self, db_session):
        PaperEngine.ensure_account(db_session, "unique_name", "hl", "s1", 1000)
        # Different strategy but same name — returns existing
        aid = PaperEngine.ensure_account(db_session, "unique_name", "hl", "s2", 2000)
        row = db_session.get(AccountRow, aid)
        assert row.strategy == "s1"  # Original is kept

    def test_active_default_true(self, db_session):
        aid = PaperEngine.ensure_account(db_session, "a", "hl", "s", 1000)
        row = db_session.get(AccountRow, aid)
        assert row.active is True

    def test_toggle_active(self, db_session):
        aid = PaperEngine.ensure_account(db_session, "a", "hl", "s", 1000)
        row = db_session.get(AccountRow, aid)
        row.active = False
        db_session.commit()
        db_session.refresh(row)
        assert row.active is False

    def test_multiple_accounts_same_strategy_exchange(self, db_session):
        """Multiple accounts can have the same (exchange, strategy) with different names."""
        aid1 = PaperEngine.ensure_account(db_session, "acct_a", "hl", "s", 5000)
        aid2 = PaperEngine.ensure_account(db_session, "acct_b", "hl", "s", 5000)
        assert aid1 != aid2


# ── Portfolio Membership ──────────────────────────────────────


class TestPortfolioMembership:
    def test_create_portfolio(self, db_session):
        pf = PortfolioGroupRow(name="my_portfolio", description="Test portfolio",
                               created_at=NOW)
        db_session.add(pf)
        db_session.commit()
        db_session.refresh(pf)
        assert pf.id is not None
        assert pf.name == "my_portfolio"

    def test_add_account_to_portfolio(self, db_session):
        pf = PortfolioGroupRow(name="pf", created_at=NOW)
        db_session.add(pf)
        db_session.commit()

        aid = PaperEngine.ensure_account(db_session, "a", "hl", "s", 1000)

        member = PortfolioMemberRow(portfolio_id=pf.id, account_id=aid)
        db_session.add(member)
        db_session.commit()

        members = db_session.query(PortfolioMemberRow).filter(
            PortfolioMemberRow.portfolio_id == pf.id
        ).all()
        assert len(members) == 1
        assert members[0].account_id == aid

    def test_remove_account_from_portfolio(self, db_session):
        pf = PortfolioGroupRow(name="pf", created_at=NOW)
        db_session.add(pf)
        db_session.commit()

        aid = PaperEngine.ensure_account(db_session, "a", "hl", "s", 1000)
        member = PortfolioMemberRow(portfolio_id=pf.id, account_id=aid)
        db_session.add(member)
        db_session.commit()

        db_session.delete(member)
        db_session.commit()

        members = db_session.query(PortfolioMemberRow).filter(
            PortfolioMemberRow.portfolio_id == pf.id
        ).all()
        assert len(members) == 0

    def test_account_in_multiple_portfolios(self, db_session):
        pf1 = PortfolioGroupRow(name="pf1", created_at=NOW)
        pf2 = PortfolioGroupRow(name="pf2", created_at=NOW)
        db_session.add_all([pf1, pf2])
        db_session.commit()

        aid = PaperEngine.ensure_account(db_session, "a", "hl", "s", 1000)
        db_session.add(PortfolioMemberRow(portfolio_id=pf1.id, account_id=aid))
        db_session.add(PortfolioMemberRow(portfolio_id=pf2.id, account_id=aid))
        db_session.commit()

        # Account appears in both portfolios
        m1 = db_session.query(PortfolioMemberRow).filter(
            PortfolioMemberRow.portfolio_id == pf1.id
        ).all()
        m2 = db_session.query(PortfolioMemberRow).filter(
            PortfolioMemberRow.portfolio_id == pf2.id
        ).all()
        assert len(m1) == 1
        assert len(m2) == 1

    def test_unique_membership(self, db_session):
        """Cannot add same account to same portfolio twice."""
        pf = PortfolioGroupRow(name="pf", created_at=NOW)
        db_session.add(pf)
        db_session.commit()

        aid = PaperEngine.ensure_account(db_session, "a", "hl", "s", 1000)
        db_session.add(PortfolioMemberRow(portfolio_id=pf.id, account_id=aid))
        db_session.commit()

        with pytest.raises(Exception):  # IntegrityError from UNIQUE constraint
            db_session.add(PortfolioMemberRow(portfolio_id=pf.id, account_id=aid))
            db_session.commit()
        db_session.rollback()


# ── Multi-Engine Signal Routing ───────────────────────────────


class TestMultiEngineSignalRouting:
    def test_each_engine_consumes_own_signals(self, db_session):
        """Two engines with different strategies only consume matching signals."""
        engine_fr, _ = _make_engine(db_session, strategy="funding_rate", name="e_fr")
        engine_rsi, _ = _make_engine(db_session, strategy="rsi_mean_reversion", name="e_rsi")

        _seed_signal(db_session, strategy="funding_rate", acted_on=False)
        _seed_signal(db_session, strategy="rsi_mean_reversion", acted_on=False)

        signals_fr = engine_fr.consume_signals(db_session)
        signals_rsi = engine_rsi.consume_signals(db_session)

        assert len(signals_fr) == 1
        assert signals_fr[0].strategy == "funding_rate"
        assert len(signals_rsi) == 1
        assert signals_rsi[0].strategy == "rsi_mean_reversion"

    def test_signals_marked_acted_per_engine(self, db_session):
        """After engine A consumes its signals, engine B still sees its own."""
        engine_a, _ = _make_engine(db_session, strategy="funding_rate", name="e_a")
        engine_b, _ = _make_engine(db_session, strategy="rsi_mean_reversion", name="e_b")

        _seed_signal(db_session, strategy="funding_rate", acted_on=False)
        _seed_signal(db_session, strategy="rsi_mean_reversion", acted_on=False)

        # A consumes first
        engine_a.consume_signals(db_session)

        # B should still see its signal (not marked by A)
        signals_b = engine_b.consume_signals(db_session)
        assert len(signals_b) == 1

    def test_exchange_scoping(self, db_session):
        """Engine scoped to polymarket only sees polymarket signals."""
        engine_hl, _ = _make_engine(db_session, exchange="hyperliquid",
                                     strategy="funding_rate", name="e_hl")
        engine_pm, _ = _make_engine(db_session, exchange="polymarket",
                                     strategy="contrarian_pure", name="e_pm")

        _seed_signal(db_session, exchange="hyperliquid", strategy="funding_rate")
        _seed_signal(db_session, exchange="polymarket", strategy="contrarian_pure")

        sigs_hl = engine_hl.consume_signals(db_session)
        sigs_pm = engine_pm.consume_signals(db_session)

        assert len(sigs_hl) == 1
        assert sigs_hl[0].exchange == "hyperliquid"
        assert len(sigs_pm) == 1
        assert sigs_pm[0].exchange == "polymarket"


# ── Account-Scoped Equity ─────────────────────────────────────


class TestAccountEquity:
    def test_initial_equity(self, db_session):
        engine, _ = _make_engine(db_session, initial_capital=5000)
        equity = engine.get_current_equity(db_session)
        assert float(equity) == pytest.approx(5000.0)

    def test_equity_after_closed_position(self, db_session):
        engine, aid = _make_engine(db_session, initial_capital=10000)
        _seed_candle(db_session, "BTC", Decimal("60000"))

        # Open and close a winning position
        pos = AccountPositionRow(
            account_id=aid, strategy="funding_rate", asset="BTC",
            exchange="hyperliquid", direction="LONG", entry_price=60000,
            entry_ts=NOW, quantity=0.5, status="OPEN", metadata_={},
        )
        db_session.add(pos)
        db_session.commit()
        db_session.refresh(pos)

        engine.close_position(db_session, pos, Decimal("61000"), "take_profit")

        equity = engine.get_current_equity(db_session)
        # 10000 + (61000 - 60000) * 0.5 = 10500
        assert float(equity) == pytest.approx(10500.0)

    def test_equity_isolated_between_accounts(self, db_session):
        """Each account's equity is independent of other accounts."""
        engine_a, aid_a = _make_engine(db_session, name="acct_a", initial_capital=10000)
        engine_b, aid_b = _make_engine(db_session, name="acct_b", initial_capital=5000)

        # Add a closed position to account A
        pos = AccountPositionRow(
            account_id=aid_a, strategy="funding_rate", asset="BTC",
            exchange="hyperliquid", direction="LONG", entry_price=60000,
            entry_ts=NOW, quantity=1.0, exit_price=61000,
            exit_ts=NOW + timedelta(minutes=30), exit_reason="take_profit",
            realised_pnl=1000.0, status="CLOSED", metadata_={},
        )
        db_session.add(pos)
        db_session.commit()

        equity_a = engine_a.get_current_equity(db_session)
        equity_b = engine_b.get_current_equity(db_session)

        assert float(equity_a) == pytest.approx(11000.0)  # 10000 + 1000
        assert float(equity_b) == pytest.approx(5000.0)   # Unaffected


# ── Portfolio Aggregation ─────────────────────────────────────


class TestPortfolioAggregation:
    def test_aggregate_equity_from_members(self, db_session):
        """Portfolio equity is the sum of member account equities."""
        _, aid_a = _make_engine(db_session, name="acct_a", initial_capital=10000)
        _, aid_b = _make_engine(db_session, name="acct_b", initial_capital=5000)

        # Create portfolio with both accounts
        pf = PortfolioGroupRow(name="combined", created_at=NOW)
        db_session.add(pf)
        db_session.commit()
        db_session.add(PortfolioMemberRow(portfolio_id=pf.id, account_id=aid_a))
        db_session.add(PortfolioMemberRow(portfolio_id=pf.id, account_id=aid_b))
        db_session.commit()

        # Write MTM for each account
        db_session.add(AccountMarkToMarketRow(
            account_id=aid_a, ts=NOW, total_equity=10500,
            unrealised_pnl=500, realised_pnl=0, open_positions=1,
        ))
        db_session.add(AccountMarkToMarketRow(
            account_id=aid_b, ts=NOW, total_equity=4800,
            unrealised_pnl=-200, realised_pnl=0, open_positions=1,
        ))
        db_session.commit()

        # Query portfolio equity by aggregating members
        members = db_session.query(PortfolioMemberRow).filter(
            PortfolioMemberRow.portfolio_id == pf.id
        ).all()
        total_equity = 0.0
        for m in members:
            mtm = db_session.query(AccountMarkToMarketRow).filter(
                AccountMarkToMarketRow.account_id == m.account_id
            ).order_by(AccountMarkToMarketRow.ts.desc()).first()
            if mtm:
                total_equity += float(mtm.total_equity)

        assert total_equity == pytest.approx(15300.0)  # 10500 + 4800
