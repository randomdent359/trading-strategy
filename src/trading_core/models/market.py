"""Market data models — candles, funding, Polymarket snapshots."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class OHLCV(BaseModel):
    """One candlestick bar."""

    exchange: str
    asset: str
    interval: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class FundingSnapshot(BaseModel):
    """A point-in-time funding rate observation."""

    exchange: str
    asset: str
    ts: datetime
    funding_rate: Decimal
    open_interest: Decimal | None = None
    mark_price: Decimal | None = None


class PolymarketMarket(BaseModel):
    """A snapshot of a Polymarket prediction market."""

    market_id: str
    market_title: str
    asset: str
    ts: datetime
    yes_price: Decimal | None = None
    no_price: Decimal | None = None
    volume_24h: Decimal | None = None
    liquidity: Decimal | None = None
    end_date: datetime | None = None


class MarketSnapshot(BaseModel):
    """Pre-fetched bundle of market data for one asset, passed to strategies."""

    asset: str
    ts: datetime
    candles: list[OHLCV] = []
    funding: list[FundingSnapshot] = []
    polymarket: list[PolymarketMarket] = []
