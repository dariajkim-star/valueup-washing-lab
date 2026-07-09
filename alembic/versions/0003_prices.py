"""prices table

Revision ID: 0003_prices
Revises: 0002_company_financials
Create Date: 2026-07-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_prices"
down_revision: str | None = "0002_company_financials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prices",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "corp_code",
            sa.String(length=8),
            sa.ForeignKey("company.corp_code"),
            nullable=False,
            index=True,
        ),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("close", sa.BigInteger),
        sa.Column("volume", sa.BigInteger),
        sa.Column("trading_value", sa.BigInteger),
        sa.Column("market_cap", sa.BigInteger),
        sa.UniqueConstraint("corp_code", "date", name="uq_prices_corp_date"),
        sa.CheckConstraint(
            "(close IS NULL OR close >= 0) AND (volume IS NULL OR volume >= 0) "
            "AND (trading_value IS NULL OR trading_value >= 0) "
            "AND (market_cap IS NULL OR market_cap >= 0)",
            name="ck_prices_nonneg",
        ),
    )


def downgrade() -> None:
    op.drop_table("prices")
