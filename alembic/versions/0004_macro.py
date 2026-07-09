"""macro_indicator table

Revision ID: 0004_macro
Revises: 0003_prices
Create Date: 2026-07-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_macro"
down_revision: str | None = "0003_prices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "macro_indicator",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("indicator", sa.String(length=30), nullable=False, index=True),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("value", sa.Float),
        sa.Column("frequency", sa.String(length=1)),
        sa.UniqueConstraint("indicator", "date", name="uq_macro_indicator_date"),
        sa.CheckConstraint(
            "indicator IN ('base_rate','bond_3y','usd_krw','leading_index')",
            name="ck_macro_indicator_allowed",
        ),
    )


def downgrade() -> None:
    op.drop_table("macro_indicator")
