"""Snapshot builder — queries DB and assembles MarketSnapshot per asset."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import desc
from sqlalchemy.orm import Session

from trading_core.db.tables.market_data import (
    CandleRow,
    FundingSnapshotRow,
    PolymarketMarketRow,
)
from trading_core.models import (
    FundingSnapshot,
    MarketSnapshot,
    OHLCV,
    PolymarketMarket,
)


def build_snapshot(
    session: Session,
    asset: str,
    *,
    candle_limit: int = 100,
    funding_days: int = 7,
    polymarket_limit: int = 10,
) -> MarketSnapshot:
    """Query Postgres and return a MarketSnapshot for a single asset.

    Args:
        session: SQLAlchemy session.
        asset: Asset ticker (e.g. "BTC").
        candle_limit: Max number of 1m candles to include (most recent).
        funding_days: Days of historical funding snapshots to fetch.
        polymarket_limit: Max number of Polymarket observations.
    """
    now = datetime.now(timezone.utc)

    # ── Candles (most recent N, ordered by time ascending) ──
    candle_rows = (
        session.query(CandleRow)
        .filter(CandleRow.asset == asset)
        .order_by(desc(CandleRow.open_time))
        .limit(candle_limit)
        .all()
    )
    candles = [
        OHLCV(
            exchange=r.exchange,
            asset=r.asset,
            interval=r.interval,
            open_time=r.open_time,
            open=Decimal(str(r.open)),
            high=Decimal(str(r.high)),
            low=Decimal(str(r.low)),
            close=Decimal(str(r.close)),
            volume=Decimal(str(r.volume)),
        )
        for r in reversed(candle_rows)  # oldest first
    ]

    # ── Funding snapshots (last N days) ──
    cutoff = now - timedelta(days=funding_days)
    funding_rows = (
        session.query(FundingSnapshotRow)
        .filter(FundingSnapshotRow.asset == asset, FundingSnapshotRow.ts >= cutoff)
        .order_by(FundingSnapshotRow.ts)
        .all()
    )
    funding = [
        FundingSnapshot(
            exchange=r.exchange,
            asset=r.asset,
            ts=r.ts,
            funding_rate=Decimal(str(r.funding_rate)),
            open_interest=Decimal(str(r.open_interest)) if r.open_interest is not None else None,
            mark_price=Decimal(str(r.mark_price)) if r.mark_price is not None else None,
        )
        for r in funding_rows
    ]

    # ── Polymarket observations (most recent N) ──
    poly_rows = (
        session.query(PolymarketMarketRow)
        .filter(PolymarketMarketRow.asset == asset)
        .order_by(desc(PolymarketMarketRow.ts))
        .limit(polymarket_limit)
        .all()
    )
    polymarket = [
        PolymarketMarket(
            market_id=r.market_id,
            market_title=r.market_title,
            asset=r.asset,
            ts=r.ts,
            yes_price=Decimal(str(r.yes_price)) if r.yes_price is not None else None,
            no_price=Decimal(str(r.no_price)) if r.no_price is not None else None,
            volume_24h=Decimal(str(r.volume_24h)) if r.volume_24h is not None else None,
            liquidity=Decimal(str(r.liquidity)) if r.liquidity is not None else None,
        )
        for r in reversed(poly_rows)  # oldest first
    ]

    return MarketSnapshot(
        asset=asset,
        ts=now,
        candles=candles,
        funding=funding,
        polymarket=polymarket,
    )
