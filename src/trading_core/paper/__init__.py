"""Paper trading engine — real-price P&L from strategy signals."""

from trading_core.paper.engine import PaperEngine
from trading_core.paper.oracle import PriceEntry, PriceOracle
from trading_core.paper.pricing import get_latest_price
from trading_core.paper.risk import RiskTracker, RiskVerdict, evaluate_risk
from trading_core.paper.sizing import (
    calculate_kelly_allocation,
    calculate_kelly_fraction,
    calculate_pnl,
    calculate_position_size,
    calculate_position_size_kelly,
    calculate_stop_price,
    calculate_take_profit_price,
    confidence_to_win_prob,
)

__all__ = [
    "PaperEngine",
    "PriceEntry",
    "PriceOracle",
    "RiskTracker",
    "RiskVerdict",
    "evaluate_risk",
    "get_latest_price",
    "calculate_kelly_allocation",
    "calculate_kelly_fraction",
    "calculate_pnl",
    "calculate_position_size",
    "calculate_position_size_kelly",
    "calculate_stop_price",
    "calculate_take_profit_price",
    "confidence_to_win_prob",
]
