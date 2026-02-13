"""Create trading_accounts schema with accounts, portfolios, positions, and MTM tables.

Revision ID: 003
Revises: 002
Create Date: 2026-02-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "trading_accounts"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # accounts
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("exchange", sa.Text, nullable=False),
        sa.Column("strategy", sa.Text, nullable=False),
        sa.Column("initial_capital", sa.Numeric, nullable=False, server_default="10000"),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.UniqueConstraint("name"),
        schema=SCHEMA,
    )

    # portfolios
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("name"),
        schema=SCHEMA,
    )

    # portfolio_members (many-to-many)
    op.create_table(
        "portfolio_members",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "portfolio_id", sa.Integer,
            sa.ForeignKey(f"{SCHEMA}.portfolios.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "account_id", sa.Integer,
            sa.ForeignKey(f"{SCHEMA}.accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("portfolio_id", "account_id"),
        schema=SCHEMA,
    )

    # positions (per-account)
    op.create_table(
        "account_positions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "account_id", sa.Integer,
            sa.ForeignKey(f"{SCHEMA}.accounts.id"),
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
            "signal_id", sa.BigInteger,
            sa.ForeignKey("trading_signals.signals.id"),
            nullable=True,
        ),
        sa.Column("metadata", JSONB, nullable=True),
        schema=SCHEMA,
    )

    # mark_to_market (per-account)
    op.create_table(
        "account_mark_to_market",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "account_id", sa.Integer,
            sa.ForeignKey(f"{SCHEMA}.accounts.id"),
            nullable=False,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_equity", sa.Numeric, nullable=False),
        sa.Column("unrealised_pnl", sa.Numeric, nullable=False),
        sa.Column("realised_pnl", sa.Numeric, nullable=False),
        sa.Column("open_positions", sa.Integer, nullable=False),
        sa.Column("breakdown", JSONB, nullable=True),
        schema=SCHEMA,
    )

    # ── Data migration: create accounts from existing positions ─────
    conn = op.get_bind()

    # Find distinct (exchange, strategy) pairs from trading_paper.positions
    existing = conn.execute(
        sa.text(
            "SELECT DISTINCT exchange, strategy "
            "FROM trading_paper.positions "
            "ORDER BY exchange, strategy"
        )
    ).fetchall()

    if existing:
        # Get initial capital from the default portfolio
        capital_row = conn.execute(
            sa.text("SELECT initial_capital FROM trading_paper.portfolio WHERE name = 'default' LIMIT 1")
        ).fetchone()
        total_capital = float(capital_row[0]) if capital_row else 10000.0
        per_account_capital = total_capital / len(existing)

        # Create an account per (exchange, strategy)
        for exch, strat in existing:
            name = f"{strat}_{exch}"
            conn.execute(
                sa.text(
                    f"INSERT INTO {SCHEMA}.accounts (name, exchange, strategy, initial_capital, active, created_at) "
                    "VALUES (:name, :exchange, :strategy, :capital, true, NOW())"
                ),
                {"name": name, "exchange": exch, "strategy": strat, "capital": per_account_capital},
            )

        # Copy positions into new schema with account_id
        conn.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.account_positions "
                "(account_id, strategy, asset, exchange, direction, entry_price, entry_ts, "
                "quantity, exit_price, exit_ts, exit_reason, realised_pnl, status, signal_id, metadata) "
                "SELECT a.id, p.strategy, p.asset, p.exchange, p.direction, p.entry_price, p.entry_ts, "
                "p.quantity, p.exit_price, p.exit_ts, p.exit_reason, p.realised_pnl, p.status, p.signal_id, p.metadata "
                f"FROM trading_paper.positions p "
                f"JOIN {SCHEMA}.accounts a ON a.exchange = p.exchange AND a.strategy = p.strategy"
            )
        )

        # Create a 'default' portfolio and add all accounts
        conn.execute(
            sa.text(f"INSERT INTO {SCHEMA}.portfolios (name, description, created_at) "
                    "VALUES ('default', 'Auto-created from migration', NOW())")
        )
        conn.execute(
            sa.text(
                f"INSERT INTO {SCHEMA}.portfolio_members (portfolio_id, account_id) "
                f"SELECT p.id, a.id FROM {SCHEMA}.portfolios p, {SCHEMA}.accounts a "
                "WHERE p.name = 'default'"
            )
        )


def downgrade() -> None:
    op.drop_table("account_mark_to_market", schema=SCHEMA)
    op.drop_table("account_positions", schema=SCHEMA)
    op.drop_table("portfolio_members", schema=SCHEMA)
    op.drop_table("portfolios", schema=SCHEMA)
    op.drop_table("accounts", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
