"""Tests for the PriceOracle — cache, staleness, DB fallback, and engine integration."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from trading_core.config.schema import PaperConfig
from trading_core.db.tables.market_data import CandleRow, PolymarketMarketRow
from trading_core.db.tables.accounts import AccountPositionRow
from trading_core.db.tables.signals import SignalRow
from trading_core.paper.engine import PaperEngine
from trading_core.paper.oracle import PriceEntry, PriceOracle

NOW = datetime.now(timezone.utc)

DEFAULT_CONFIG = PaperConfig(
    initial_capital=10000,
    risk_pct=0.02,
    default_stop_loss_pct=0.02,
    default_take_profit_pct=0.04,
    default_timeout_minutes=60,
    slippage_pct={"hyperliquid": 0.0, "polymarket": 0.0},
    fee_pct={"hyperliquid": 0.0, "polymarket": 0.0},
)


@pytest.fixture
def oracle():
    """A PriceOracle for BTC/ETH/SOL with generous staleness thresholds."""
    return PriceOracle(
        assets=["BTC", "ETH", "SOL"],
        staleness_threshold_s=30.0,
        pm_staleness_threshold_s=600.0,
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


def _seed_pm_market(session, asset, yes_price, minutes_ago=0):
    session.add(PolymarketMarketRow(
        market_id=f"pm-{asset}-test",
        market_title=f"Will {asset} go up?",
        asset=asset,
        ts=NOW - timedelta(minutes=minutes_ago),
        yes_price=float(yes_price),
        no_price=1.0 - float(yes_price),
        volume_24h=10000,
        liquidity=50000,
    ))
    session.commit()


def _seed_signal(session, strategy="funding_rate", asset="BTC", exchange="hyperliquid",
                 direction="LONG", entry_price=60000, acted_on=False):
    row = SignalRow(
        ts=NOW,
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


def _make_engine(session, config=None, oracle=None, initial_capital=10000,
                 exchange="hyperliquid", strategy="funding_rate"):
    cfg = config or DEFAULT_CONFIG
    aid = PaperEngine.ensure_account(
        session, name=f"test_{exchange}_{strategy}",
        exchange=exchange, strategy=strategy, initial_capital=initial_capital,
    )
    return PaperEngine(cfg, aid, exchange, strategy, oracle=oracle), aid


# ── TestStaleness ─────────────────────────────────────────────


class TestStaleness:
    def test_no_entry_is_stale(self, oracle):
        assert oracle.is_stale("BTC", "hyperliquid") is True

    def test_fresh_entry_is_not_stale(self, oracle):
        oracle.update_price("BTC", "hyperliquid", Decimal("60000"))
        assert oracle.is_stale("BTC", "hyperliquid") is False

    def test_expired_entry_is_stale(self, oracle):
        oracle.update_price("BTC", "hyperliquid", Decimal("60000"))
        # Force the entry to look old
        oracle._hl_prices["BTC"] = PriceEntry(
            price=Decimal("60000"),
            updated_at=time.monotonic() - 31,
            source="manual",
        )
        assert oracle.is_stale("BTC", "hyperliquid") is True

    def test_pm_staleness_uses_pm_threshold(self, oracle):
        oracle.update_price("BTC", "polymarket", Decimal("0.65"))
        assert oracle.is_stale("BTC", "polymarket") is False
        # Force old
        oracle._pm_prices["BTC"] = PriceEntry(
            price=Decimal("0.65"),
            updated_at=time.monotonic() - 601,
            source="manual",
        )
        assert oracle.is_stale("BTC", "polymarket") is True

    def test_unknown_exchange_is_stale(self, oracle):
        assert oracle.is_stale("BTC", "unknown_exchange") is True


# ── TestCacheHit ──────────────────────────────────────────────


class TestCacheHit:
    def test_hl_cache_hit_returns_decimal(self, oracle):
        oracle.update_price("BTC", "hyperliquid", Decimal("60123.45"))
        price = oracle.get_price("BTC", "hyperliquid")
        assert price == Decimal("60123.45")
        assert isinstance(price, Decimal)

    def test_hl_cache_miss_returns_none(self, oracle):
        price = oracle.get_price("BTC", "hyperliquid")
        assert price is None

    def test_hl_stale_cache_returns_none(self, oracle):
        oracle._hl_prices["BTC"] = PriceEntry(
            price=Decimal("60000"),
            updated_at=time.monotonic() - 31,
            source="ws",
        )
        price = oracle.get_price("BTC", "hyperliquid")
        assert price is None


# ── TestDBFallback ────────────────────────────────────────────


class TestDBFallback:
    def test_pm_falls_back_to_db(self, oracle, db_session):
        _seed_pm_market(db_session, "BTC", Decimal("0.72"))
        price = oracle.get_price("BTC", "polymarket", session=db_session)
        assert price == Decimal("0.72")

    def test_pm_db_caches_result(self, oracle, db_session):
        _seed_pm_market(db_session, "BTC", Decimal("0.72"))
        oracle.get_price("BTC", "polymarket", session=db_session)
        # Second call should use cache, not DB
        assert "BTC" in oracle._pm_prices
        assert oracle._pm_prices["BTC"].source == "db"

    def test_pm_returns_none_without_session(self, oracle):
        price = oracle.get_price("BTC", "polymarket")
        assert price is None

    def test_pm_returns_none_when_no_db_data(self, oracle, db_session):
        price = oracle.get_price("BTC", "polymarket", session=db_session)
        assert price is None

    def test_pm_cache_hit_skips_db(self, oracle, db_session):
        oracle.update_price("BTC", "polymarket", Decimal("0.80"))
        # Even though DB has different data, cache should win
        _seed_pm_market(db_session, "BTC", Decimal("0.60"))
        price = oracle.get_price("BTC", "polymarket", session=db_session)
        assert price == Decimal("0.80")


# ── TestHandleAllMids ─────────────────────────────────────────


class TestHandleAllMids:
    def test_parses_tracked_assets(self, oracle):
        oracle._handle_all_mids({
            "mids": {"BTC": "60123.5", "ETH": "3456.7", "DOGE": "0.123"},
        })
        assert oracle._hl_prices["BTC"].price == Decimal("60123.5")
        assert oracle._hl_prices["ETH"].price == Decimal("3456.7")
        # DOGE not tracked
        assert "DOGE" not in oracle._hl_prices

    def test_filters_to_tracked_assets_only(self, oracle):
        oracle._handle_all_mids({
            "mids": {"DOGE": "0.123", "SHIB": "0.00001"},
        })
        assert len(oracle._hl_prices) == 0

    def test_handles_empty_mids(self, oracle):
        oracle._handle_all_mids({})
        assert len(oracle._hl_prices) == 0

    def test_updates_existing_prices(self, oracle):
        oracle._handle_all_mids({"mids": {"BTC": "60000"}})
        oracle._handle_all_mids({"mids": {"BTC": "61000"}})
        assert oracle._hl_prices["BTC"].price == Decimal("61000")

    def test_source_is_ws(self, oracle):
        oracle._handle_all_mids({"mids": {"BTC": "60000"}})
        assert oracle._hl_prices["BTC"].source == "ws"


# ── TestPMPriceFromDB ────────────────────────────────────────


class TestPMPriceFromDB:
    def test_returns_latest_yes_price(self, db_session):
        _seed_pm_market(db_session, "BTC", Decimal("0.60"), minutes_ago=10)
        _seed_pm_market(db_session, "BTC", Decimal("0.72"), minutes_ago=0)
        price = PriceOracle._get_pm_price_from_db(db_session, "BTC")
        assert price == Decimal("0.72")

    def test_returns_none_when_no_data(self, db_session):
        price = PriceOracle._get_pm_price_from_db(db_session, "BTC")
        assert price is None

    def test_filters_by_asset(self, db_session):
        _seed_pm_market(db_session, "BTC", Decimal("0.72"))
        _seed_pm_market(db_session, "ETH", Decimal("0.55"))
        price = PriceOracle._get_pm_price_from_db(db_session, "ETH")
        assert price == Decimal("0.55")


# ── TestEngineWithOracle ─────────────────────────────────────


class TestEngineWithOracle:
    def test_engine_uses_oracle_price(self, db_session):
        """When oracle has a price, engine should use it instead of DB."""
        oracle = PriceOracle(assets=["BTC"], staleness_threshold_s=30.0)
        oracle.update_price("BTC", "hyperliquid", Decimal("60500"))

        engine, aid = _make_engine(db_session, oracle=oracle)
        signal = _seed_signal(db_session, asset="BTC", exchange="hyperliquid")
        # No candle in DB — oracle is the only source
        pos = engine.open_position(db_session, signal, Decimal("10000"))
        assert pos is not None
        # Entry price should be based on oracle's 60500 (no slippage with zeroed config)
        assert float(pos.entry_price) == pytest.approx(60500, rel=1e-4)

    def test_engine_falls_back_to_db_without_oracle(self, db_session):
        """Without oracle, engine falls back to get_latest_price (DB)."""
        engine, aid = _make_engine(db_session)
        _seed_candle(db_session, "BTC", Decimal("60000"))
        signal = _seed_signal(db_session, asset="BTC", exchange="hyperliquid")
        pos = engine.open_position(db_session, signal, Decimal("10000"))
        assert pos is not None

    def test_oracle_none_preserves_old_behavior(self, db_session):
        """Engine with oracle=None behaves identically to original."""
        engine, aid = _make_engine(db_session, oracle=None)
        signal = _seed_signal(db_session, asset="BTC", exchange="hyperliquid")
        # No candle, no oracle → no price → None
        pos = engine.open_position(db_session, signal, Decimal("10000"))
        assert pos is None

    def test_consume_signals_matches_account_exchange(self, db_session):
        """Engine only consumes signals matching its account exchange and strategy."""
        oracle = PriceOracle(assets=["BTC"], staleness_threshold_s=30.0)
        engine, aid = _make_engine(db_session, oracle=oracle, exchange="hyperliquid", strategy="funding_rate")

        _seed_signal(db_session, exchange="hyperliquid", strategy="funding_rate", acted_on=False)
        _seed_signal(db_session, exchange="polymarket", strategy="contrarian_pure", acted_on=False)

        signals = engine.consume_signals(db_session)
        assert len(signals) == 1
        assert signals[0].exchange == "hyperliquid"
        assert signals[0].strategy == "funding_rate"

    def test_pm_engine_consumes_pm_signals(self, db_session):
        """A polymarket-scoped engine consumes polymarket signals."""
        oracle = PriceOracle(assets=["BTC"], staleness_threshold_s=30.0, pm_staleness_threshold_s=600.0)
        engine, aid = _make_engine(db_session, oracle=oracle, exchange="polymarket", strategy="contrarian_pure")

        _seed_signal(db_session, exchange="hyperliquid", strategy="funding_rate", acted_on=False)
        _seed_signal(db_session, exchange="polymarket", strategy="contrarian_pure", acted_on=False)

        signals = engine.consume_signals(db_session)
        assert len(signals) == 1
        assert signals[0].exchange == "polymarket"

    def test_pm_signal_opens_position_with_oracle(self, db_session):
        """PM signal with oracle-provided price should open a position."""
        oracle = PriceOracle(
            assets=["BTC"],
            staleness_threshold_s=30.0,
            pm_staleness_threshold_s=600.0,
        )
        oracle.update_price("BTC", "polymarket", Decimal("0.72"))

        engine, aid = _make_engine(db_session, oracle=oracle, exchange="polymarket", strategy="contrarian_pure")
        signal = _seed_signal(
            db_session, asset="BTC", exchange="polymarket",
            strategy="contrarian_pure", entry_price=0.72,
        )
        pos = engine.open_position(db_session, signal, Decimal("10000"))
        assert pos is not None
        assert pos.exchange == "polymarket"
