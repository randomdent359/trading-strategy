"""Polymarket contrarian strategies — ported from legacy monitors."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from trading_core.models import MarketSnapshot, PolymarketMarket, Signal
from trading_core.strategy import Strategy, register


def _is_too_close_to_expiry(market: PolymarketMarket, min_days: int, now: datetime) -> bool:
    """Return True if the market closes within min_days of now."""
    if market.end_date is None or min_days <= 0:
        return False
    return (market.end_date - now) < timedelta(days=min_days)


def _score_market(
    market: PolymarketMarket,
    threshold: Decimal,
) -> tuple[str, float, Decimal] | None:
    """Score a single market. Returns (direction, confidence, yes_price) or None."""
    if market.yes_price is None:
        return None

    yes = market.yes_price
    if yes > threshold:
        direction = "SHORT"
        confidence = float(min((yes - threshold) / (Decimal(1) - threshold), Decimal(1)))
    elif yes < (Decimal(1) - threshold):
        direction = "LONG"
        confidence = float(min(((Decimal(1) - threshold) - yes) / (Decimal(1) - threshold), Decimal(1)))
    else:
        return None

    return direction, confidence, yes


@register
class ContrarianPure(Strategy):
    """Bet against consensus when prediction market probability exceeds threshold.

    Scans all Polymarket observations in the snapshot and emits a signal
    for the market with the strongest extreme.

    yes_price > threshold → SHORT (consensus too high, contrarian bets on "no")
    yes_price < (1 - threshold) → LONG (consensus too low, contrarian bets on "yes")
    """

    name = "contrarian_pure"
    assets = ["BTC", "ETH", "SOL"]
    exchanges = ["polymarket"]
    interval = "10m"
    docs = {
        "thesis": "Bet against consensus when prediction market probability exceeds a threshold. Extreme yes/no prices tend to revert as they overweight recent sentiment.",
        "data": "Polymarket yes_price for each market in the snapshot. Filters out markets closing within min_days_to_close.",
        "risk": "Prediction markets can stay extreme longer than expected. Illiquid markets may have wide spreads. Contrarian bets lose when consensus is correct.",
    }

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        self.threshold = Decimal(str(self.params.get("threshold", 0.72)))
        self.min_days_to_close = int(self.params.get("min_days_to_close", 7))

    def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
        if not snapshot.polymarket:
            return None

        best: tuple[str, float, Decimal, PolymarketMarket] | None = None

        for market in snapshot.polymarket:
            if _is_too_close_to_expiry(market, self.min_days_to_close, snapshot.ts):
                continue
            result = _score_market(market, self.threshold)
            if result is None:
                continue
            direction, confidence, yes = result
            if best is None or confidence > best[1]:
                best = (direction, confidence, yes, market)

        if best is None:
            return None

        direction, confidence, yes, market = best
        return Signal(
            strategy=self.name,
            asset=snapshot.asset,
            exchange="polymarket",
            direction=direction,
            confidence=confidence,
            entry_price=yes,
            metadata={
                "market_id": market.market_id,
                "market_title": market.market_title,
                "yes_price": str(yes),
                "threshold": str(self.threshold),
            },
            ts=snapshot.ts,
        )


@register
class ContrarianStrength(Strategy):
    """Higher-bar contrarian — only fires on very strong consensus (>80%).

    Scans all Polymarket observations in the snapshot and emits a signal
    for the market with the strongest extreme.
    """

    name = "contrarian_strength"
    assets = ["BTC", "ETH", "SOL"]
    exchanges = ["polymarket"]
    interval = "10m"
    docs = {
        "thesis": "Higher-conviction contrarian — only fires when consensus exceeds 80%. Trades less often but targets stronger mean-reversion setups.",
        "data": "Polymarket yes_price with a stricter threshold (default 0.80 vs 0.72). Same market filtering as ContrarianPure.",
        "risk": "Fewer signals means less diversification. Very strong consensus sometimes reflects genuine information rather than crowd bias.",
    }

    def __init__(self, **params: Any) -> None:
        super().__init__(**params)
        self.threshold = Decimal(str(self.params.get("threshold", 0.80)))
        self.min_days_to_close = int(self.params.get("min_days_to_close", 7))

    def evaluate(self, snapshot: MarketSnapshot) -> Signal | None:
        if not snapshot.polymarket:
            return None

        best: tuple[str, float, Decimal, PolymarketMarket] | None = None

        for market in snapshot.polymarket:
            if _is_too_close_to_expiry(market, self.min_days_to_close, snapshot.ts):
                continue
            result = _score_market(market, self.threshold)
            if result is None:
                continue
            direction, confidence, yes = result
            if best is None or confidence > best[1]:
                best = (direction, confidence, yes, market)

        if best is None:
            return None

        direction, confidence, yes, market = best
        return Signal(
            strategy=self.name,
            asset=snapshot.asset,
            exchange="polymarket",
            direction=direction,
            confidence=confidence,
            entry_price=yes,
            metadata={
                "market_id": market.market_id,
                "market_title": market.market_title,
                "yes_price": str(yes),
                "threshold": str(self.threshold),
            },
            ts=snapshot.ts,
        )
