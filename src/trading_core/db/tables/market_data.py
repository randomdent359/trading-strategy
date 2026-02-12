"""SQLAlchemy ORM models for the trading_market_data schema."""

from sqlalchemy import BigInteger, Numeric, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from trading_core.db.base import Base

SCHEMA = "trading_market_data"


class CandleRow(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("exchange", "asset", "interval", "open_time"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    asset: Mapped[str] = mapped_column(Text, nullable=False)
    interval: Mapped[str] = mapped_column(Text, nullable=False)
    open_time: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Numeric, nullable=False)
    high: Mapped[float] = mapped_column(Numeric, nullable=False)
    low: Mapped[float] = mapped_column(Numeric, nullable=False)
    close: Mapped[float] = mapped_column(Numeric, nullable=False)
    volume: Mapped[float] = mapped_column(Numeric, nullable=False)


class FundingSnapshotRow(Base):
    __tablename__ = "funding_snapshots"
    __table_args__ = (
        UniqueConstraint("exchange", "asset", "ts"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    asset: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    funding_rate: Mapped[float] = mapped_column(Numeric, nullable=False)
    open_interest: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    mark_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class PolymarketMarketRow(Base):
    __tablename__ = "polymarket_markets"
    __table_args__ = (
        UniqueConstraint("market_id", "ts"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(Text, nullable=False)
    market_title: Mapped[str] = mapped_column(Text, nullable=False)
    asset: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    yes_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    no_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    volume_24h: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    liquidity: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    end_date: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
