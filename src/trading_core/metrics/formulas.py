"""Pure metric computation functions — no DB, no SQLAlchemy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass
class StrategyMetrics:
    """Aggregated metrics for a strategy or portfolio."""

    total_trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    avg_hold_minutes: float = 0.0


def win_rate(wins: int, total: int) -> float:
    """Win rate as a percentage 0-100."""
    if total <= 0:
        return 0.0
    return wins / total * 100


def profit_factor(gross_profit: float, gross_loss: float) -> float:
    """Gross profit / gross loss.  *gross_loss* should be a positive number."""
    if gross_loss <= 0:
        return 0.0
    return gross_profit / gross_loss


def expectancy(win_rate_pct: float, avg_win: float, avg_loss: float) -> float:
    """Expected value per trade: wr * avg_win - (1-wr) * |avg_loss|."""
    wr = win_rate_pct / 100.0
    return wr * avg_win - (1 - wr) * abs(avg_loss)


def sharpe_ratio(returns: Sequence[float]) -> float:
    """Annualised Sharpe ratio using sample std (ddof=1)."""
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns, dtype=np.float64)
    mean = np.mean(arr)
    std = np.std(arr, ddof=1)
    if std == 0:
        return 0.0
    return float(mean / std * np.sqrt(252))


def sortino_ratio(returns: Sequence[float]) -> float:
    """Annualised Sortino ratio using downside deviation (ddof=1)."""
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns, dtype=np.float64)
    mean = np.mean(arr)
    downside = np.minimum(arr, 0.0)
    downside_std = np.std(downside, ddof=1)
    if downside_std == 0:
        return 0.0
    return float(mean / downside_std * np.sqrt(252))


def max_drawdown(equity_series: Sequence[float]) -> float:
    """Maximum drawdown as a percentage 0-100."""
    if len(equity_series) < 2:
        return 0.0
    arr = np.array(equity_series, dtype=np.float64)
    peak = np.maximum.accumulate(arr)
    # Avoid division by zero where peak is 0
    safe_peak = np.where(peak == 0, 1.0, peak)
    drawdowns = (peak - arr) / safe_peak
    return float(np.max(drawdowns) * 100)


def avg_hold_time_minutes(hold_times_seconds: Sequence[float]) -> float:
    """Average hold time in minutes from a list of hold durations in seconds."""
    if not hold_times_seconds:
        return 0.0
    return sum(hold_times_seconds) / len(hold_times_seconds) / 60.0
