"""SQLAlchemy ORM models for the trading_signals schema."""

from sqlalchemy import BigInteger, Boolean, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from trading_core.db.base import Base

SCHEMA = "trading_signals"


class SignalRow(Base):
    __tablename__ = "signals"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    strategy: Mapped[str] = mapped_column(Text, nullable=False)
    asset: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    acted_on: Mapped[bool] = mapped_column(Boolean, default=False)
