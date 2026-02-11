"""Create schemas and initial tables.

Revision ID: 001
Revises: None
Create Date: 2026-02-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Schemas are created by env.py before migrations run.

    # --- trading_market_data ---
    op.create_table(
        "candles",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("exchange", sa.Text, nullable=False),
        sa.Column("asset", sa.Text, nullable=False),
        sa.Column("interval", sa.Text, nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric, nullable=False),
        sa.Column("high", sa.Numeric, nullable=False),
        sa.Column("low", sa.Numeric, nullable=False),
        sa.Column("close", sa.Numeric, nullable=False),
        sa.Column("volume", sa.Numeric, nullable=False),
        sa.UniqueConstraint("exchange", "asset", "interval", "open_time"),
        schema="trading_market_data",
    )

    op.create_table(
        "funding_snapshots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("exchange", sa.Text, nullable=False),
        sa.Column("asset", sa.Text, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("funding_rate", sa.Numeric, nullable=False),
        sa.Column("open_interest", sa.Numeric, nullable=True),
        sa.Column("mark_price", sa.Numeric, nullable=True),
        sa.UniqueConstraint("exchange", "asset", "ts"),
        schema="trading_market_data",
    )

    op.create_table(
        "polymarket_markets",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("market_id", sa.Text, nullable=False),
        sa.Column("market_title", sa.Text, nullable=False),
        sa.Column("asset", sa.Text, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("yes_price", sa.Numeric, nullable=True),
        sa.Column("no_price", sa.Numeric, nullable=True),
        sa.Column("volume_24h", sa.Numeric, nullable=True),
        sa.Column("liquidity", sa.Numeric, nullable=True),
        sa.UniqueConstraint("market_id", "ts"),
        schema="trading_market_data",
    )

    # --- trading_signals ---
    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strategy", sa.Text, nullable=False),
        sa.Column("asset", sa.Text, nullable=False),
        sa.Column("exchange", sa.Text, nullable=False),
        sa.Column("direction", sa.Text, nullable=True),
        sa.Column("confidence", sa.Numeric, nullable=True),
        sa.Column("entry_price", sa.Numeric, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("acted_on", sa.Boolean, default=False),
        schema="trading_signals",
    )

    # --- trading_paper ---
    op.create_table(
        "portfolio",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("initial_capital", sa.Numeric, nullable=False, server_default="10000"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        schema="trading_paper",
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "portfolio_id",
            sa.Integer,
            sa.ForeignKey("trading_paper.portfolio.id"),
            nullable=False,
        ),
        sa.Column("strategy", sa.Text, nullable=False),
        sa.Column("asset", sa.Text, nullable=False),
        sa.Column("exchange", sa.Text, nullable=False),
        sa.Column("direction", sa.Text, nullable=False),
        sa.Column("entry_price", sa.Numeric, nullable=False),
        sa.Column("entry_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity", sa.Numeric, nullable=False),
        sa.Column("exit_price", sa.Numeric, nullable=True),
        sa.Column("exit_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_reason", sa.Text, nullable=True),
        sa.Column("realised_pnl", sa.Numeric, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="OPEN"),
        sa.Column(
            "signal_id",
            sa.BigInteger,
            sa.ForeignKey("trading_signals.signals.id"),
            nullable=True,
        ),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        schema="trading_paper",
    )

    op.create_table(
        "mark_to_market",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "portfolio_id",
            sa.Integer,
            sa.ForeignKey("trading_paper.portfolio.id"),
            nullable=False,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_equity", sa.Numeric, nullable=False),
        sa.Column("unrealised_pnl", sa.Numeric, nullable=False),
        sa.Column("realised_pnl", sa.Numeric, nullable=False),
        sa.Column("open_positions", sa.Integer, nullable=False),
        sa.Column("breakdown", postgresql.JSONB, nullable=True),
        schema="trading_paper",
    )


def downgrade() -> None:
    op.drop_table("mark_to_market", schema="trading_paper")
    op.drop_table("positions", schema="trading_paper")
    op.drop_table("portfolio", schema="trading_paper")
    op.drop_table("signals", schema="trading_signals")
    op.drop_table("polymarket_markets", schema="trading_market_data")
    op.drop_table("funding_snapshots", schema="trading_market_data")
    op.drop_table("candles", schema="trading_market_data")
