"""Paper trading engine — real-price P&L from strategy signals."""

from trading_core.paper.engine import PaperEngine
from trading_core.paper.pricing import get_latest_price
from trading_core.paper.sizing import (
    calculate_pnl,
    calculate_position_size,
    calculate_stop_price,
    calculate_take_profit_price,
)

__all__ = [
    "PaperEngine",
    "get_latest_price",
    "calculate_pnl",
    "calculate_position_size",
    "calculate_stop_price",
    "calculate_take_profit_price",
]
