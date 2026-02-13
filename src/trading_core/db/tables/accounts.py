"""SQLAlchemy ORM models for the trading_accounts schema."""

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, Numeric, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import DateTime

from trading_core.db.base import Base

SCHEMA = "trading_accounts"


class AccountRow(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("name"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    strategy: Mapped[str] = mapped_column(Text, nullable=False)
    initial_capital: Mapped[float] = mapped_column(Numeric, nullable=False, default=10000)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)


class PortfolioGroupRow(Base):
    __tablename__ = "portfolios"
    __table_args__ = (
        UniqueConstraint("name"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PortfolioMemberRow(Base):
    __tablename__ = "portfolio_members"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "account_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{SCHEMA}.portfolios.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{SCHEMA}.accounts.id", ondelete="CASCADE"),
        nullable=False,
    )


class AccountPositionRow(Base):
    __tablename__ = "account_positions"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{SCHEMA}.accounts.id"),
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


class AccountMarkToMarketRow(Base):
    __tablename__ = "account_mark_to_market"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(f"{SCHEMA}.accounts.id"),
        nullable=False,
    )
    ts: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_equity: Mapped[float] = mapped_column(Numeric, nullable=False)
    unrealised_pnl: Mapped[float] = mapped_column(Numeric, nullable=False)
    realised_pnl: Mapped[float] = mapped_column(Numeric, nullable=False)
    open_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    breakdown: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
