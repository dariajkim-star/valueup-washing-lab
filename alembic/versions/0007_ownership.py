"""ownership table

Revision ID: 0007_ownership
Revises: 0006_valueup_plan
Create Date: 2026-07-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_ownership"
down_revision: str | None = "0006_valueup_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ownership",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "corp_code",
            sa.String(length=8),
            sa.ForeignKey("company.corp_code"),
            nullable=False,
            index=True,
        ),
        sa.Column("as_of", sa.String(length=10), nullable=False),
        sa.Column("largest_shareholder_pct", sa.Float),
        sa.Column("treasury_stock_pct", sa.Float),
        sa.UniqueConstraint("corp_code", "as_of", name="uq_ownership_corp_asof"),
    )


def downgrade() -> None:
    op.drop_table("ownership")
