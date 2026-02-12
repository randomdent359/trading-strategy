"""Position sizing and P&L calculations — pure functions, no DB."""

from __future__ import annotations

from decimal import Decimal

from trading_core.config.schema import PaperConfig


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


def calculate_kelly_fraction(
    confidence: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    safety_factor: float = 0.5,
) -> float:
    """Calculate Kelly fraction for position sizing.

    b = take_profit_pct / stop_loss_pct  (reward-to-risk ratio)
    kelly = (p * b - (1-p)) / b          where p = confidence
    adjusted = kelly * safety_factor      (half-Kelly by default)

    Returns 0.0 if stop_loss_pct is zero or the edge is non-positive.
    """
    if stop_loss_pct == 0:
        return 0.0
    b = take_profit_pct / stop_loss_pct
    if b == 0:
        return 0.0
    kelly = (confidence * b - (1 - confidence)) / b
    if kelly <= 0:
        return 0.0
    return kelly * safety_factor


def confidence_to_win_prob(confidence: float, base_rate: float = 0.5) -> float:
    """Map signal confidence (0–1) to win probability for Kelly.

    p = base_rate + confidence * (1 - base_rate)

    confidence=0 → p=base_rate (neutral edge),
    confidence=1 → p=1.0 (certainty).
    """
    return base_rate + confidence * (1.0 - base_rate)


def calculate_kelly_allocation(
    confidence: float | None,
    config: PaperConfig,
) -> float:
    """Return Kelly allocation fraction (% of equity as position notional).

    Maps confidence → win probability, feeds into Kelly formula, returns
    the fraction of equity to allocate as position notional value.
    Returns 0.0 if Kelly is disabled, confidence is None, or there is no edge.
    """
    if not config.kelly_enabled or confidence is None:
        return 0.0
    win_prob = confidence_to_win_prob(
        float(confidence), config.kelly_base_win_prob,
    )
    kelly = calculate_kelly_fraction(
        confidence=win_prob,
        stop_loss_pct=config.default_stop_loss_pct,
        take_profit_pct=config.default_take_profit_pct,
        safety_factor=config.kelly_safety_factor,
    )
    return kelly


def calculate_position_size_kelly(
    entry_price: Decimal,
    equity: Decimal,
    kelly_allocation: float,
    risk_pct: float,
    stop_loss_pct: float,
) -> Decimal:
    """Calculate position quantity using Kelly allocation with a risk cap.

    notional = equity * kelly_allocation
    max_notional = (equity * risk_pct) / stop_loss_pct   (risk cap)
    quantity = min(notional, max_notional) / entry_price
    """
    if entry_price == 0 or kelly_allocation <= 0:
        return Decimal("0")
    notional = equity * Decimal(str(kelly_allocation))
    max_notional = (equity * Decimal(str(risk_pct))) / Decimal(str(stop_loss_pct))
    return min(notional, max_notional) / entry_price


def apply_slippage(
    price: Decimal,
    direction: str,
    slippage_pct: float,
    is_entry: bool,
) -> Decimal:
    """Apply slippage to a price based on direction and entry/exit.

    For entries:
    - LONG: pay more (price * (1 + slippage))
    - SHORT: receive less (price * (1 - slippage))

    For exits:
    - LONG: receive less (price * (1 - slippage))
    - SHORT: pay more (price * (1 + slippage))
    """
    slippage = Decimal(str(slippage_pct))

    if is_entry:
        if direction == "LONG":
            return price * (1 + slippage)
        else:  # SHORT
            return price * (1 - slippage)
    else:  # exit
        if direction == "LONG":
            return price * (1 - slippage)
        else:  # SHORT
            return price * (1 + slippage)


def calculate_fees(
    entry_price: Decimal,
    exit_price: Decimal,
    quantity: Decimal,
    fee_pct: float,
) -> Decimal:
    """Calculate total fees for a round-trip trade.

    Fees are charged on notional value at both entry and exit.
    """
    fee_rate = Decimal(str(fee_pct))
    entry_notional = entry_price * quantity
    exit_notional = exit_price * quantity
    return (entry_notional + exit_notional) * fee_rate
