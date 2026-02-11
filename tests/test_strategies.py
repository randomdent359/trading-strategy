"""Tests for all concrete strategy implementations."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trading_core.models import FundingSnapshot, MarketSnapshot, PolymarketMarket
from trading_core.strategy.strategies.contrarian import ContrarianPure, ContrarianStrength
from trading_core.strategy.strategies.funding import FundingOI, FundingRate

NOW = datetime.now(timezone.utc)


def _pm_snapshot(asset: str, yes: str) -> MarketSnapshot:
    """Helper: MarketSnapshot with a single Polymarket observation."""
    return MarketSnapshot(
        asset=asset,
        ts=NOW,
        polymarket=[
            PolymarketMarket(
                market_id="test-123",
                market_title=f"Will {asset} go up?",
                asset=asset,
                ts=NOW,
                yes_price=Decimal(yes),
                no_price=Decimal(str(1 - float(yes))),
            )
        ],
    )


def _funding_snapshot(
    asset: str,
    rate: str,
    oi: str | None = None,
    mark: str = "60000",
) -> FundingSnapshot:
    return FundingSnapshot(
        exchange="hyperliquid",
        asset=asset,
        ts=NOW,
        funding_rate=Decimal(rate),
        open_interest=Decimal(oi) if oi else None,
        mark_price=Decimal(mark),
    )


def _hl_snapshot(
    asset: str,
    funding: list[FundingSnapshot] | None = None,
) -> MarketSnapshot:
    return MarketSnapshot(asset=asset, ts=NOW, funding=funding or [])


# ── Contrarian Pure ─────────────────────────────────────────────


class TestContrarianPure:
    def test_high_consensus_short(self):
        s = ContrarianPure(threshold=0.72)
        sig = s.evaluate(_pm_snapshot("BTC", "0.85"))
        assert sig is not None
        assert sig.direction == "SHORT"

    def test_low_consensus_long(self):
        s = ContrarianPure(threshold=0.72)
        sig = s.evaluate(_pm_snapshot("BTC", "0.20"))
        assert sig is not None
        assert sig.direction == "LONG"

    def test_within_threshold_no_signal(self):
        s = ContrarianPure(threshold=0.72)
        sig = s.evaluate(_pm_snapshot("BTC", "0.50"))
        assert sig is None

    def test_no_polymarket_data(self):
        s = ContrarianPure()
        sig = s.evaluate(MarketSnapshot(asset="BTC", ts=NOW))
        assert sig is None

    def test_custom_threshold(self):
        s = ContrarianPure(threshold=0.90)
        # 0.85 is below 0.90, should not fire
        assert s.evaluate(_pm_snapshot("BTC", "0.85")) is None
        # 0.95 is above 0.90, should fire
        sig = s.evaluate(_pm_snapshot("BTC", "0.95"))
        assert sig is not None
        assert sig.direction == "SHORT"


# ── Contrarian Strength ─────────────────────────────────────────


class TestContrarianStrength:
    def test_fires_at_80_pct(self):
        s = ContrarianStrength(threshold=0.80)
        sig = s.evaluate(_pm_snapshot("ETH", "0.88"))
        assert sig is not None
        assert sig.direction == "SHORT"

    def test_no_signal_at_75_pct(self):
        s = ContrarianStrength(threshold=0.80)
        sig = s.evaluate(_pm_snapshot("ETH", "0.75"))
        assert sig is None

    def test_low_side_long(self):
        s = ContrarianStrength(threshold=0.80)
        sig = s.evaluate(_pm_snapshot("SOL", "0.10"))
        assert sig is not None
        assert sig.direction == "LONG"


# ── Funding Rate ────────────────────────────────────────────────


class TestFundingRate:
    def test_high_positive_funding_short(self):
        s = FundingRate(threshold=0.0012)
        snap = _hl_snapshot("BTC", [_funding_snapshot("BTC", "0.002", mark="60000")])
        sig = s.evaluate(snap)
        assert sig is not None
        assert sig.direction == "SHORT"
        assert sig.entry_price == Decimal("60000")

    def test_high_negative_funding_long(self):
        s = FundingRate(threshold=0.0012)
        snap = _hl_snapshot("ETH", [_funding_snapshot("ETH", "-0.002", mark="3000")])
        sig = s.evaluate(snap)
        assert sig is not None
        assert sig.direction == "LONG"

    def test_normal_funding_no_signal(self):
        s = FundingRate(threshold=0.0012)
        snap = _hl_snapshot("BTC", [_funding_snapshot("BTC", "0.0005")])
        assert s.evaluate(snap) is None

    def test_no_funding_data(self):
        s = FundingRate()
        assert s.evaluate(MarketSnapshot(asset="BTC", ts=NOW)) is None

    def test_confidence_capped_at_1(self):
        s = FundingRate(threshold=0.0012)
        snap = _hl_snapshot("BTC", [_funding_snapshot("BTC", "0.01", mark="60000")])
        sig = s.evaluate(snap)
        assert sig is not None
        assert sig.confidence <= 1.0


# ── Funding + OI ────────────────────────────────────────────────


class TestFundingOI:
    def _oi_snapshot(self, rate: str, current_oi: str, max_oi: str) -> MarketSnapshot:
        """Build snapshot with historical OI for ratio calculation."""
        funding_data = [
            _funding_snapshot("BTC", "0.0001", oi=max_oi, mark="60000"),
            _funding_snapshot("BTC", rate, oi=current_oi, mark="60000"),
        ]
        return _hl_snapshot("BTC", funding_data)

    def test_both_conditions_met_short(self):
        s = FundingOI(funding_threshold=0.0015, oi_pct=85)
        snap = self._oi_snapshot("0.002", "95", "100")  # oi_ratio = 95%
        sig = s.evaluate(snap)
        assert sig is not None
        assert sig.direction == "SHORT"

    def test_both_conditions_met_negative_long(self):
        s = FundingOI(funding_threshold=0.0015, oi_pct=85)
        snap = self._oi_snapshot("-0.002", "95", "100")
        sig = s.evaluate(snap)
        assert sig is not None
        assert sig.direction == "LONG"

    def test_funding_below_threshold_no_signal(self):
        s = FundingOI(funding_threshold=0.0015, oi_pct=85)
        snap = self._oi_snapshot("0.001", "95", "100")
        assert s.evaluate(snap) is None

    def test_oi_below_threshold_no_signal(self):
        s = FundingOI(funding_threshold=0.0015, oi_pct=85)
        snap = self._oi_snapshot("0.002", "50", "100")  # oi_ratio = 50%
        assert s.evaluate(snap) is None

    def test_no_oi_data(self):
        s = FundingOI()
        snap = _hl_snapshot("BTC", [_funding_snapshot("BTC", "0.003")])
        assert s.evaluate(snap) is None
