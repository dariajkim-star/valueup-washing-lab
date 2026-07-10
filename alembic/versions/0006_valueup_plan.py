"""valueup_plan table

Revision ID: 0006_valueup_plan
Revises: 0005_valuation_metrics_view
Create Date: 2026-07-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_valueup_plan"
down_revision: str | None = "0005_valuation_metrics_view"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "valueup_plan",
        sa.Column("plan_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "corp_code",
            sa.String(length=8),
            sa.ForeignKey("company.corp_code"),
            nullable=False,
            index=True,
        ),
        sa.Column("disclosure_date", sa.String(length=10), nullable=False),
        sa.Column("target_roe", sa.Float),
        sa.Column("target_payout_ratio", sa.Float),
        sa.Column("target_pbr", sa.Float),
        sa.Column("period_start", sa.String(length=10)),
        sa.Column("period_end", sa.String(length=10)),
        sa.Column("buyback_planned", sa.Boolean),
        sa.Column("raw_text", sa.Text),
        sa.UniqueConstraint(
            "corp_code", "disclosure_date", name="uq_valueup_corp_date"
        ),
    )


def downgrade() -> None:
    op.drop_table("valueup_plan")
