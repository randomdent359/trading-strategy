"""Add end_date column to polymarket_markets.

Revision ID: 002
Revises: 001
Create Date: 2026-02-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "polymarket_markets",
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        schema="trading_market_data",
    )


def downgrade() -> None:
    op.drop_column("polymarket_markets", "end_date", schema="trading_market_data")
