"""Import all table modules so Base.metadata knows about them."""

from trading_core.db.tables.accounts import (
    AccountMarkToMarketRow,
    AccountPositionRow,
    AccountRow,
    PortfolioGroupRow,
    PortfolioMemberRow,
)
from trading_core.db.tables.market_data import CandleRow, FundingSnapshotRow, PolymarketMarketRow
from trading_core.db.tables.signals import SignalRow
from trading_core.db.tables.paper import MarkToMarketRow, PortfolioRow, PositionRow

__all__ = [
    "AccountMarkToMarketRow",
    "AccountPositionRow",
    "AccountRow",
    "CandleRow",
    "FundingSnapshotRow",
    "MarkToMarketRow",
    "PolymarketMarketRow",
    "PortfolioGroupRow",
    "PortfolioMemberRow",
    "PortfolioRow",
    "PositionRow",
    "SignalRow",
]
