"""Import all table modules so Base.metadata knows about them."""

from trading_core.db.tables.market_data import CandleRow, FundingSnapshotRow, PolymarketMarketRow
from trading_core.db.tables.signals import SignalRow
from trading_core.db.tables.paper import MarkToMarketRow, PortfolioRow, PositionRow

__all__ = [
    "CandleRow",
    "FundingSnapshotRow",
    "MarkToMarketRow",
    "PolymarketMarketRow",
    "PortfolioRow",
    "PositionRow",
    "SignalRow",
]
