"""Price lookup — reads latest candle close from the database."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import desc
from sqlalchemy.orm import Session

from trading_core.db.tables.market_data import CandleRow


def get_latest_price(
    session: Session,
    asset: str,
    exchange: str = "hyperliquid",
) -> Decimal | None:
    """Return the most recent candle close for an asset, or None if no data."""
    row = (
        session.query(CandleRow.close)
        .filter(CandleRow.asset == asset, CandleRow.exchange == exchange)
        .order_by(desc(CandleRow.open_time))
        .limit(1)
        .scalar()
    )
    if row is None:
        return None
    return Decimal(str(row))
