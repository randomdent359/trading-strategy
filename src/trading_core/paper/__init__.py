"""Paper trading engine — real-price P&L from strategy signals."""

from trading_core.paper.engine import PaperEngine
from trading_core.paper.pricing import get_latest_price
from trading_core.paper.risk import RiskTracker, RiskVerdict, evaluate_risk
from trading_core.paper.sizing import (
    calculate_adjusted_risk_pct,
    calculate_kelly_fraction,
    calculate_pnl,
    calculate_position_size,
    calculate_stop_price,
    calculate_take_profit_price,
)

__all__ = [
    "PaperEngine",
    "RiskTracker",
    "RiskVerdict",
    "evaluate_risk",
    "get_latest_price",
    "calculate_adjusted_risk_pct",
    "calculate_kelly_fraction",
    "calculate_pnl",
    "calculate_position_size",
    "calculate_stop_price",
    "calculate_take_profit_price",
]
