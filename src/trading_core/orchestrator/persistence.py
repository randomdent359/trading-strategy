"""Signal persistence — write Signal Pydantic models to the signals table."""

from __future__ import annotations

from sqlalchemy.orm import Session

from trading_core.db.tables.signals import SignalRow
from trading_core.models import Signal


def persist_signal(session: Session, signal: Signal) -> int:
    """Insert a Signal into trading_signals.signals and return the row id."""
    row = SignalRow(
        ts=signal.ts,
        strategy=signal.strategy,
        asset=signal.asset,
        exchange=signal.exchange,
        direction=signal.direction,
        confidence=signal.confidence,
        entry_price=signal.entry_price,
        metadata_=signal.metadata,
        acted_on=False,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row.id
