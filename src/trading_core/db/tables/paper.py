"""SQLAlchemy ORM models for the trading_paper schema."""

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from trading_core.db.base import Base

SCHEMA = "trading_paper"


class PortfolioRow(Base):
    __tablename__ = "portfolio"
    __table_args__ = (
        UniqueConstraint("name"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    initial_capital: Mapped[float] = mapped_column(Numeric, nullable=False, default=10000)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PositionRow(Base):
    __tablename__ = "positions"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{SCHEMA}.portfolio.id"),
        nullable=False,
    )
    strategy: Mapped[str] = mapped_column(Text, nullable=False)
    asset: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric, nullable=False)
    entry_ts: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    exit_ts: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    realised_pnl: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="OPEN")
    signal_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("trading_signals.signals.id"),
        nullable=True,
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)


class MarkToMarketRow(Base):
    __tablename__ = "mark_to_market"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{SCHEMA}.portfolio.id"),
        nullable=False,
    )
    ts: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_equity: Mapped[float] = mapped_column(Numeric, nullable=False)
    unrealised_pnl: Mapped[float] = mapped_column(Numeric, nullable=False)
    realised_pnl: Mapped[float] = mapped_column(Numeric, nullable=False)
    open_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
