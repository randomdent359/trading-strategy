"""Tests for risk controls and Kelly criterion sizing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import BigInteger, Integer, JSON, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from trading_core.config.schema import PaperConfig
from trading_core.db.base import Base
from trading_core.db.tables.market_data import CandleRow
from trading_core.db.tables.paper import PortfolioRow, PositionRow
from trading_core.db.tables.signals import SignalRow
from trading_core.paper.engine import PaperEngine
from trading_core.paper.risk import (
    RiskTracker,
    RiskVerdict,
    check_max_positions_per_strategy,
    check_max_total_exposure,
    evaluate_risk,
)
from trading_core.paper.sizing import (
    calculate_kelly_allocation,
    calculate_kelly_fraction,
    calculate_position_size_kelly,
    confidence_to_win_prob,
)

NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

DEFAULT_CONFIG = PaperConfig(
    initial_capital=10000,
    risk_pct=0.02,
    default_stop_loss_pct=0.02,
    default_take_profit_pct=0.04,
    default_timeout_minutes=60,
    max_positions_per_strategy=3,
    max_total_exposure_pct=0.50,
    max_daily_loss_per_strategy=500.0,
    cooldown_after_loss_minutes=5,
    kelly_enabled=False,
    kelly_safety_factor=0.5,
)


@pytest.fixture
def db_session():
    """In-memory SQLite session with all schemas/tables created."""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _rec):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

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


def _seed_signal(
    session,
    strategy="funding_rate",
    asset="BTC",
    exchange="hyperliquid",
    direction="LONG",
    entry_price=60000,
    confidence=0.8,
    acted_on=False,
    minutes_ago=0,
):
    row = SignalRow(
        ts=NOW - timedelta(minutes=minutes_ago),
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


def _make_engine(session, config=None, initial_capital=10000):
    cfg = config or DEFAULT_CONFIG
    pid = PaperEngine.ensure_portfolio(session, name="default", initial_capital=initial_capital)
    return PaperEngine(cfg, pid), pid


def _open_position_directly(session, portfolio_id, strategy="funding_rate", asset="BTC",
                            direction="LONG", entry_price=60000, quantity=0.1667):
    pos = PositionRow(
        portfolio_id=portfolio_id,
        strategy=strategy,
        asset=asset,
        exchange="hyperliquid",
        direction=direction,
        entry_price=entry_price,
        entry_ts=NOW,
        quantity=quantity,
        status="OPEN",
        metadata_={},
    )
    session.add(pos)
    session.commit()
    session.refresh(pos)
    return pos


# ── TestKellyFraction ─────────────────────────────────────────


class TestKellyFraction:
    def test_high_confidence_capped(self):
        # confidence=0.8, SL=2%, TP=4% → b=2, kelly=(0.8*2-0.2)/2=0.7, half=0.35
        # But this is the raw fraction — capping happens in calculate_adjusted_risk_pct
        result = calculate_kelly_fraction(0.8, 0.02, 0.04, safety_factor=0.5)
        assert result == pytest.approx(0.35, rel=1e-3)

    def test_low_confidence_reduced(self):
        # confidence=0.35, b=2, kelly=(0.35*2-0.65)/2=0.025, half=0.0125
        result = calculate_kelly_fraction(0.35, 0.02, 0.04, safety_factor=0.5)
        assert result == pytest.approx(0.0125, rel=1e-3)

    def test_no_edge_returns_zero(self):
        # confidence=0.25, b=2, kelly=(0.25*2-0.75)/2=-0.125 → 0.0
        result = calculate_kelly_fraction(0.25, 0.02, 0.04, safety_factor=0.5)
        assert result == 0.0

    def test_safety_factor_scales_linearly(self):
        full = calculate_kelly_fraction(0.6, 0.02, 0.04, safety_factor=1.0)
        half = calculate_kelly_fraction(0.6, 0.02, 0.04, safety_factor=0.5)
        assert half == pytest.approx(full * 0.5, rel=1e-6)

    def test_zero_stop_loss_returns_zero(self):
        result = calculate_kelly_fraction(0.8, 0.0, 0.04, safety_factor=0.5)
        assert result == 0.0

    def test_zero_take_profit_returns_zero(self):
        # b=0 → returns 0.0
        result = calculate_kelly_fraction(0.8, 0.02, 0.0, safety_factor=0.5)
        assert result == 0.0

    def test_breakeven_confidence(self):
        # confidence=1/3 with b=2 → kelly=(1/3*2 - 2/3)/2 = 0 → 0.0
        result = calculate_kelly_fraction(1/3, 0.02, 0.04, safety_factor=0.5)
        assert result == pytest.approx(0.0, abs=1e-10)


# ── TestConfidenceToWinProb ────────────────────────────────────


class TestConfidenceToWinProb:
    def test_zero_confidence(self):
        assert confidence_to_win_prob(0.0, 0.5) == 0.5

    def test_full_confidence(self):
        assert confidence_to_win_prob(1.0, 0.5) == 1.0

    def test_mid_confidence(self):
        # 0.5 + 0.5 * 0.5 = 0.75
        assert confidence_to_win_prob(0.5, 0.5) == 0.75

    def test_linearity(self):
        # p should scale linearly between base_rate and 1.0
        p1 = confidence_to_win_prob(0.2, 0.5)
        p2 = confidence_to_win_prob(0.4, 0.5)
        p3 = confidence_to_win_prob(0.6, 0.5)
        assert p2 - p1 == pytest.approx(p3 - p2, rel=1e-6)

    def test_custom_base_rate(self):
        # base_rate=0.4, confidence=0.5 → 0.4 + 0.5*0.6 = 0.7
        assert confidence_to_win_prob(0.5, 0.4) == pytest.approx(0.7)


# ── TestCalculateKellyAllocation ──────────────────────────────


class TestCalculateKellyAllocation:
    def test_kelly_disabled_returns_zero(self):
        config = DEFAULT_CONFIG.model_copy(update={"kelly_enabled": False})
        result = calculate_kelly_allocation(0.8, config)
        assert result == 0.0

    def test_kelly_enabled_no_confidence_returns_zero(self):
        config = DEFAULT_CONFIG.model_copy(update={"kelly_enabled": True})
        result = calculate_kelly_allocation(None, config)
        assert result == 0.0

    def test_kelly_zero_confidence_has_edge(self):
        # confidence=0 → win_prob=0.5, b=2, kelly=(0.5*2-0.5)/2=0.25, half=0.125
        config = DEFAULT_CONFIG.model_copy(update={"kelly_enabled": True})
        result = calculate_kelly_allocation(0.0, config)
        assert result == pytest.approx(0.125, rel=1e-3)

    def test_kelly_mid_confidence(self):
        # confidence=0.3 → win_prob=0.65, b=2, kelly=(0.65*2-0.35)/2=0.475, half=0.2375
        config = DEFAULT_CONFIG.model_copy(update={"kelly_enabled": True})
        result = calculate_kelly_allocation(0.3, config)
        assert result == pytest.approx(0.2375, rel=1e-3)

    def test_kelly_high_confidence(self):
        # confidence=1.0 → win_prob=1.0, b=2, kelly=(1.0*2-0.0)/2=1.0, half=0.5
        config = DEFAULT_CONFIG.model_copy(update={"kelly_enabled": True})
        result = calculate_kelly_allocation(1.0, config)
        assert result == pytest.approx(0.5, rel=1e-3)

    def test_respects_base_win_prob_config(self):
        config = DEFAULT_CONFIG.model_copy(update={
            "kelly_enabled": True, "kelly_base_win_prob": 0.4,
        })
        # confidence=0 → win_prob=0.4, b=2, kelly=(0.4*2-0.6)/2=0.1, half=0.05
        result = calculate_kelly_allocation(0.0, config)
        assert result == pytest.approx(0.05, rel=1e-3)


# ── TestCalculatePositionSizeKelly ────────────────────────────


class TestCalculatePositionSizeKelly:
    def test_basic_sizing(self):
        # equity=10000, kelly_alloc=0.125, notional=1250, entry=100000
        # max_notional = (10000*0.02)/0.02 = 10000
        # qty = 1250/100000 = 0.0125
        qty = calculate_position_size_kelly(
            Decimal("100000"), Decimal("10000"), 0.125, 0.02, 0.02,
        )
        assert float(qty) == pytest.approx(0.0125, rel=1e-6)

    def test_risk_cap_binding(self):
        # equity=10000, kelly_alloc=0.8, notional=8000, entry=100000
        # max_notional = (10000*0.02)/0.02 = 10000 → not binding
        # But with risk_pct=0.01: max_notional = (10000*0.01)/0.02 = 5000 → binding
        qty = calculate_position_size_kelly(
            Decimal("100000"), Decimal("10000"), 0.8, 0.01, 0.02,
        )
        # min(8000, 5000) = 5000, qty = 5000/100000 = 0.05
        assert float(qty) == pytest.approx(0.05, rel=1e-6)

    def test_zero_allocation_returns_zero(self):
        qty = calculate_position_size_kelly(
            Decimal("100000"), Decimal("10000"), 0.0, 0.02, 0.02,
        )
        assert qty == Decimal("0")

    def test_zero_entry_price_returns_zero(self):
        qty = calculate_position_size_kelly(
            Decimal("0"), Decimal("10000"), 0.125, 0.02, 0.02,
        )
        assert qty == Decimal("0")


# ── TestCheckMaxPositionsPerStrategy ──────────────────────────


class TestCheckMaxPositionsPerStrategy:
    def test_below_limit(self, db_session):
        engine, pid = _make_engine(db_session)
        _open_position_directly(db_session, pid, strategy="funding_rate")
        positions = db_session.query(PositionRow).filter(PositionRow.status == "OPEN").all()
        verdict = check_max_positions_per_strategy("funding_rate", positions, 3)
        assert verdict.allowed is True

    def test_at_limit(self, db_session):
        engine, pid = _make_engine(db_session)
        for _ in range(3):
            _open_position_directly(db_session, pid, strategy="funding_rate")
        positions = db_session.query(PositionRow).filter(PositionRow.status == "OPEN").all()
        verdict = check_max_positions_per_strategy("funding_rate", positions, 3)
        assert verdict.allowed is False
        assert "max_positions_per_strategy" in verdict.reason

    def test_different_strategy_not_counted(self, db_session):
        engine, pid = _make_engine(db_session)
        for _ in range(3):
            _open_position_directly(db_session, pid, strategy="funding_rate")
        positions = db_session.query(PositionRow).filter(PositionRow.status == "OPEN").all()
        verdict = check_max_positions_per_strategy("rsi_mean_reversion", positions, 3)
        assert verdict.allowed is True


# ── TestCheckMaxTotalExposure ─────────────────────────────────


class TestCheckMaxTotalExposure:
    def test_below_limit(self, db_session):
        engine, pid = _make_engine(db_session)
        # One position: 60000 * 0.1 = 6000 notional, equity=10000, limit=50%=5000
        # But let's use small positions to stay under
        _open_position_directly(db_session, pid, entry_price=1000, quantity=1)
        positions = db_session.query(PositionRow).filter(PositionRow.status == "OPEN").all()
        # Current exposure: 1000. Adding 1000. Total: 2000 < 5000
        verdict = check_max_total_exposure(positions, Decimal("10000"), Decimal("1000"), 0.50)
        assert verdict.allowed is True

    def test_above_limit(self, db_session):
        engine, pid = _make_engine(db_session)
        _open_position_directly(db_session, pid, entry_price=3000, quantity=1)
        positions = db_session.query(PositionRow).filter(PositionRow.status == "OPEN").all()
        # Current exposure: 3000. Adding 3000. Total: 6000 > 5000
        verdict = check_max_total_exposure(positions, Decimal("10000"), Decimal("3000"), 0.50)
        assert verdict.allowed is False
        assert "max_total_exposure" in verdict.reason

    def test_boundary_exactly_at_limit(self, db_session):
        engine, pid = _make_engine(db_session)
        _open_position_directly(db_session, pid, entry_price=2000, quantity=1)
        positions = db_session.query(PositionRow).filter(PositionRow.status == "OPEN").all()
        # Current: 2000. Adding 3000. Total: 5000 == limit 5000. Not exceeded.
        verdict = check_max_total_exposure(positions, Decimal("10000"), Decimal("3000"), 0.50)
        assert verdict.allowed is True


# ── TestRiskTracker ───────────────────────────────────────────


class TestRiskTracker:
    def test_no_loss_no_cooldown(self):
        tracker = RiskTracker(DEFAULT_CONFIG)
        assert tracker.is_in_cooldown("funding_rate", NOW) is False

    def test_loss_triggers_cooldown(self):
        tracker = RiskTracker(DEFAULT_CONFIG)
        tracker.record_close("funding_rate", -100.0, NOW)
        assert tracker.is_in_cooldown("funding_rate", NOW + timedelta(seconds=30)) is True

    def test_cooldown_expires(self):
        tracker = RiskTracker(DEFAULT_CONFIG)
        tracker.record_close("funding_rate", -100.0, NOW)
        # After 5 minutes cooldown should be over
        assert tracker.is_in_cooldown("funding_rate", NOW + timedelta(minutes=6)) is False

    def test_daily_loss_triggers_pause(self):
        tracker = RiskTracker(DEFAULT_CONFIG)
        # Accumulate losses > 500
        tracker.record_close("funding_rate", -300.0, NOW)
        tracker.record_close("funding_rate", -250.0, NOW + timedelta(minutes=1))
        assert tracker.is_strategy_paused("funding_rate", NOW + timedelta(minutes=2)) is True

    def test_new_day_resets_pause(self):
        tracker = RiskTracker(DEFAULT_CONFIG)
        tracker.record_close("funding_rate", -600.0, NOW)
        assert tracker.is_strategy_paused("funding_rate", NOW) is True
        # Next day
        next_day = NOW + timedelta(days=1)
        assert tracker.is_strategy_paused("funding_rate", next_day) is False

    def test_wins_offset_losses(self):
        tracker = RiskTracker(DEFAULT_CONFIG)
        tracker.record_close("funding_rate", -400.0, NOW)
        tracker.record_close("funding_rate", 200.0, NOW + timedelta(minutes=1))
        # Net loss = 400 - 200 = 200, below 500 threshold
        assert tracker.is_strategy_paused("funding_rate", NOW + timedelta(minutes=2)) is False

    def test_strategies_are_independent(self):
        tracker = RiskTracker(DEFAULT_CONFIG)
        tracker.record_close("funding_rate", -600.0, NOW)
        assert tracker.is_strategy_paused("funding_rate", NOW) is True
        assert tracker.is_strategy_paused("rsi_mean_reversion", NOW) is False
        assert tracker.is_in_cooldown("rsi_mean_reversion", NOW) is False


# ── TestEvaluateRisk ──────────────────────────────────────────


class TestEvaluateRisk:
    def test_all_pass(self, db_session):
        tracker = RiskTracker(DEFAULT_CONFIG)
        verdict = evaluate_risk(
            DEFAULT_CONFIG, tracker, "funding_rate",
            open_positions=[], equity=Decimal("10000"),
            new_position_value=Decimal("1000"), now=NOW,
        )
        assert verdict.allowed is True

    def test_reject_daily_loss(self, db_session):
        tracker = RiskTracker(DEFAULT_CONFIG)
        tracker.record_close("funding_rate", -600.0, NOW)
        verdict = evaluate_risk(
            DEFAULT_CONFIG, tracker, "funding_rate",
            open_positions=[], equity=Decimal("10000"),
            new_position_value=Decimal("1000"), now=NOW,
        )
        assert verdict.allowed is False
        assert "daily_loss" in verdict.reason

    def test_reject_cooldown(self, db_session):
        tracker = RiskTracker(DEFAULT_CONFIG)
        tracker.record_close("funding_rate", -50.0, NOW)  # small loss, won't trigger pause
        verdict = evaluate_risk(
            DEFAULT_CONFIG, tracker, "funding_rate",
            open_positions=[], equity=Decimal("10000"),
            new_position_value=Decimal("1000"), now=NOW + timedelta(seconds=30),
        )
        assert verdict.allowed is False
        assert "cooldown" in verdict.reason

    def test_reject_max_positions(self, db_session):
        engine, pid = _make_engine(db_session)
        for _ in range(3):
            _open_position_directly(db_session, pid, strategy="funding_rate")
        positions = db_session.query(PositionRow).filter(PositionRow.status == "OPEN").all()
        tracker = RiskTracker(DEFAULT_CONFIG)
        verdict = evaluate_risk(
            DEFAULT_CONFIG, tracker, "funding_rate",
            open_positions=positions, equity=Decimal("10000"),
            new_position_value=Decimal("1000"), now=NOW,
        )
        assert verdict.allowed is False
        assert "max_positions_per_strategy" in verdict.reason

    def test_reject_max_exposure(self, db_session):
        engine, pid = _make_engine(db_session)
        _open_position_directly(db_session, pid, entry_price=4000, quantity=1)
        positions = db_session.query(PositionRow).filter(PositionRow.status == "OPEN").all()
        tracker = RiskTracker(DEFAULT_CONFIG)
        verdict = evaluate_risk(
            DEFAULT_CONFIG, tracker, "funding_rate",
            open_positions=positions, equity=Decimal("10000"),
            new_position_value=Decimal("2000"), now=NOW,
        )
        assert verdict.allowed is False
        assert "max_total_exposure" in verdict.reason

    def test_priority_daily_loss_before_cooldown(self, db_session):
        """Daily loss pause is checked before cooldown."""
        tracker = RiskTracker(DEFAULT_CONFIG)
        tracker.record_close("funding_rate", -600.0, NOW)
        # Both paused and in cooldown — daily_loss should be the reason
        verdict = evaluate_risk(
            DEFAULT_CONFIG, tracker, "funding_rate",
            open_positions=[], equity=Decimal("10000"),
            new_position_value=Decimal("1000"), now=NOW + timedelta(seconds=30),
        )
        assert verdict.allowed is False
        assert "daily_loss" in verdict.reason


# ── TestEngineRiskIntegration ─────────────────────────────────


class TestEngineRiskIntegration:
    def test_max_positions_rejects_signal(self, db_session):
        engine, pid = _make_engine(db_session)
        _seed_candle(db_session, "BTC", Decimal("60000"))
        for _ in range(3):
            _open_position_directly(db_session, pid, strategy="funding_rate")
        signal = _seed_signal(db_session, strategy="funding_rate")
        equity = engine.get_current_equity(db_session)
        verdict = engine.check_risk(db_session, signal, equity, NOW)
        assert verdict.allowed is False
        assert "max_positions_per_strategy" in verdict.reason

    def test_different_strategy_accepted(self, db_session):
        # Use high exposure limit — this test is about strategy position count independence
        config = DEFAULT_CONFIG.model_copy(update={"max_total_exposure_pct": 10.0})
        engine, pid = _make_engine(db_session, config=config)
        _seed_candle(db_session, "BTC", Decimal("60000"))
        for _ in range(3):
            _open_position_directly(db_session, pid, strategy="funding_rate")
        signal = _seed_signal(db_session, strategy="rsi_mean_reversion")
        equity = engine.get_current_equity(db_session)
        verdict = engine.check_risk(db_session, signal, equity, NOW)
        assert verdict.allowed is True

    def test_kelly_low_confidence_opens_position(self, db_session):
        config = DEFAULT_CONFIG.model_copy(update={"kelly_enabled": True})
        engine, pid = _make_engine(db_session, config=config)
        _seed_candle(db_session, "BTC", Decimal("60000"))

        signal = _seed_signal(db_session, strategy="funding_rate", confidence=0.10)
        pos = engine.open_position(db_session, signal, Decimal("10000"))
        assert pos is not None
        # confidence=0.10 → win_prob=0.55, b=2, kelly=(0.55*2-0.45)/2=0.325, half=0.1625
        # notional = 10000*0.1625 = 1625, max_notional = (10000*0.02)/0.02 = 10000
        # qty = 1625/60000 ≈ 0.02708
        assert float(pos.quantity) == pytest.approx(0.02708, rel=1e-2)

    def test_kelly_zero_confidence_opens_position(self, db_session):
        config = DEFAULT_CONFIG.model_copy(update={"kelly_enabled": True})
        engine, pid = _make_engine(db_session, config=config)
        _seed_candle(db_session, "BTC", Decimal("60000"))

        signal = _seed_signal(db_session, strategy="funding_rate", confidence=0.0)
        pos = engine.open_position(db_session, signal, Decimal("10000"))
        assert pos is not None
        # confidence=0 → win_prob=0.5, kelly_alloc=0.125
        # notional = 10000*0.125 = 1250, qty = 1250/60000 ≈ 0.02083
        assert float(pos.quantity) == pytest.approx(0.02083, rel=1e-2)

    def test_kelly_high_confidence_larger_position(self, db_session):
        config = DEFAULT_CONFIG.model_copy(update={"kelly_enabled": True})
        engine, pid = _make_engine(db_session, config=config)
        _seed_candle(db_session, "BTC", Decimal("60000"))

        signal = _seed_signal(db_session, strategy="funding_rate", confidence=0.8)
        pos = engine.open_position(db_session, signal, Decimal("10000"))
        assert pos is not None
        # confidence=0.8 → win_prob=0.9, b=2, kelly=(0.9*2-0.1)/2=0.85, half=0.425
        # notional = 10000*0.425 = 4250, max_notional = 10000 → not binding
        # qty = 4250/60000 ≈ 0.07083
        assert float(pos.quantity) == pytest.approx(0.07083, rel=1e-2)

    def test_daily_loss_pause_after_stop_losses(self, db_session):
        engine, pid = _make_engine(db_session)
        _seed_candle(db_session, "BTC", Decimal("60000"))

        # Simulate closing 3 positions with -200 each = -600 total
        for _ in range(3):
            pos = _open_position_directly(db_session, pid, strategy="funding_rate",
                                          entry_price=60000, quantity=1.0)
            engine.close_position(db_session, pos, Decimal("59800"), "stop_loss")

        signal = _seed_signal(db_session, strategy="funding_rate")
        equity = engine.get_current_equity(db_session)
        # Use a time well after close_position's datetime.now() calls
        # to be outside cooldown but still on same day
        check_time = datetime.now(timezone.utc) + timedelta(minutes=10)
        verdict = engine.check_risk(db_session, signal, equity, check_time)
        assert verdict.allowed is False
        assert "daily_loss" in verdict.reason

    def test_cooldown_blocks_immediate_reentry(self, db_session):
        engine, pid = _make_engine(db_session)
        _seed_candle(db_session, "BTC", Decimal("60000"))

        # Single small loss — triggers cooldown but not daily pause
        pos = _open_position_directly(db_session, pid, strategy="funding_rate",
                                      entry_price=60000, quantity=0.1)
        engine.close_position(db_session, pos, Decimal("59800"), "stop_loss")

        signal = _seed_signal(db_session, strategy="funding_rate")
        equity = engine.get_current_equity(db_session)
        # Immediately after loss — should be in cooldown
        verdict = engine.check_risk(db_session, signal, equity,
                                    datetime.now(timezone.utc))
        assert verdict.allowed is False
        assert "cooldown" in verdict.reason
