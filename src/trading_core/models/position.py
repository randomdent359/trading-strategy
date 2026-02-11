"""Position and portfolio models for paper trading."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class Portfolio(BaseModel):
    """A paper trading portfolio."""

    name: str
    initial_capital: Decimal = Decimal("10000")
    created_at: datetime | None = None


class Position(BaseModel):
    """An open or closed paper trading position."""

    portfolio_id: int
    strategy: str
    asset: str
    exchange: str
    direction: Literal["LONG", "SHORT"]
    entry_price: Decimal
    entry_ts: datetime
    quantity: Decimal
    exit_price: Decimal | None = None
    exit_ts: datetime | None = None
    exit_reason: Literal["signal", "stop_loss", "take_profit", "timeout"] | None = None
    realised_pnl: Decimal | None = None
    status: Literal["OPEN", "CLOSED"] = "OPEN"
    signal_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarkToMarket(BaseModel):
    """A point-in-time portfolio valuation snapshot."""

    portfolio_id: int
    ts: datetime
    total_equity: Decimal
    unrealised_pnl: Decimal
    realised_pnl: Decimal
    open_positions: int
    breakdown: dict[str, Any] = Field(default_factory=dict)
