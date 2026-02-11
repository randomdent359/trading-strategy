"""Signal model — emitted by strategies."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class Signal(BaseModel):
    """A trading signal emitted by a strategy."""

    strategy: str
    asset: str
    exchange: str
    direction: Literal["LONG", "SHORT"]
    confidence: float = Field(ge=0.0, le=1.0)
    entry_price: Decimal
    metadata: dict[str, Any] = Field(default_factory=dict)
    ts: datetime
