"""Position sizing and P&L calculations — pure functions, no DB."""

from __future__ import annotations

from decimal import Decimal


def calculate_position_size(
    entry_price: Decimal,
    equity: Decimal,
    risk_pct: float,
    stop_loss_pct: float,
) -> Decimal:
    """Calculate position quantity based on fixed-fractional risk.

    risk_amount = equity * risk_pct
    stop_distance = entry_price * stop_loss_pct
    quantity = risk_amount / stop_distance
    """
    stop_distance = entry_price * Decimal(str(stop_loss_pct))
    risk_amount = equity * Decimal(str(risk_pct))
    if stop_distance == 0:
        return Decimal("0")
    return risk_amount / stop_distance


def calculate_pnl(
    direction: str,
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
) -> Decimal:
    """Calculate realised P&L for a closed position.

    LONG:  (exit - entry) * qty
    SHORT: (entry - exit) * qty
    """
    if direction == "LONG":
        return (exit_price - entry_price) * quantity
    else:
        return (entry_price - exit_price) * quantity


def calculate_stop_price(
    direction: str,
    entry_price: Decimal,
    stop_loss_pct: float,
) -> Decimal:
    """Calculate stop-loss trigger price.

    LONG:  entry * (1 - pct)
    SHORT: entry * (1 + pct)
    """
    pct = Decimal(str(stop_loss_pct))
    if direction == "LONG":
        return entry_price * (1 - pct)
    else:
        return entry_price * (1 + pct)


def calculate_take_profit_price(
    direction: str,
    entry_price: Decimal,
    take_profit_pct: float,
) -> Decimal:
    """Calculate take-profit trigger price.

    LONG:  entry * (1 + pct)
    SHORT: entry * (1 - pct)
    """
    pct = Decimal(str(take_profit_pct))
    if direction == "LONG":
        return entry_price * (1 + pct)
    else:
        return entry_price * (1 - pct)
