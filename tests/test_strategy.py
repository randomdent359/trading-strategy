"""Tests for Strategy ABC and registry."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trading_core.models import MarketSnapshot, Signal
from trading_core.strategy import Strategy, register
from trading_core.strategy.registry import STRATEGY_REGISTRY

NOW = datetime.now(timezone.utc)


class TestStrategyABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            Strategy()

    def test_concrete_strategy(self):
        class DummyStrategy(Strategy):
            name = "dummy"
            assets = ["BTC"]
            exchanges = ["hyperliquid"]
            interval = "1m"

            def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
                return Signal(
                    strategy=self.name,
                    asset=snapshot.asset,
                    exchange="hyperliquid",
                    direction="LONG",
                    confidence=0.9,
                    entry_price=Decimal("60000"),
                    ts=snapshot.ts,
                )

        s = DummyStrategy()
        snap = MarketSnapshot(asset="BTC", ts=NOW)
        signal = s.evaluate(snap)
        assert signal is not None
        assert signal.direction == "LONG"
        assert signal.strategy == "dummy"

    def test_strategy_can_return_none(self):
        class PassStrategy(Strategy):
            name = "passer"
            assets = ["BTC"]
            exchanges = ["hyperliquid"]
            interval = "5m"

            def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
                return None

        s = PassStrategy()
        snap = MarketSnapshot(asset="BTC", ts=NOW)
        assert s.evaluate(snap) is None


class TestRegistry:
    def setup_method(self):
        # Clean registry between tests
        STRATEGY_REGISTRY.clear()

    def test_register_decorator(self):
        @register
        class TestStrat(Strategy):
            name = "test_strat"
            assets = ["BTC"]
            exchanges = ["hyperliquid"]
            interval = "1m"

            def evaluate(self, snapshot):
                return None

        assert "test_strat" in STRATEGY_REGISTRY
        assert STRATEGY_REGISTRY["test_strat"] is TestStrat

    def test_register_returns_class(self):
        @register
        class AnotherStrat(Strategy):
            name = "another"
            assets = ["ETH"]
            exchanges = ["hyperliquid"]
            interval = "5m"

            def evaluate(self, snapshot):
                return None

        assert AnotherStrat.name == "another"

    def test_duplicate_name_raises(self):
        @register
        class First(Strategy):
            name = "dup"
            assets = ["BTC"]
            exchanges = ["hyperliquid"]
            interval = "1m"

            def evaluate(self, snapshot):
                return None

        with pytest.raises(ValueError, match="Duplicate strategy name"):

            @register
            class Second(Strategy):
                name = "dup"
                assets = ["BTC"]
                exchanges = ["hyperliquid"]
                interval = "1m"

                def evaluate(self, snapshot):
                    return None

    def test_missing_name_raises(self):
        with pytest.raises(ValueError, match="must define a 'name' attribute"):

            @register
            class NoName(Strategy):
                name = ""
                assets = ["BTC"]
                exchanges = ["hyperliquid"]
                interval = "1m"

                def evaluate(self, snapshot):
                    return None

    def test_multiple_strategies(self):
        @register
        class StratA(Strategy):
            name = "strat_a"
            assets = ["BTC"]
            exchanges = ["hyperliquid"]
            interval = "1m"

            def evaluate(self, snapshot):
                return None

        @register
        class StratB(Strategy):
            name = "strat_b"
            assets = ["ETH", "SOL"]
            exchanges = ["polymarket"]
            interval = "5m"

            def evaluate(self, snapshot):
                return None

        assert len(STRATEGY_REGISTRY) == 2
        assert set(STRATEGY_REGISTRY.keys()) == {"strat_a", "strat_b"}
