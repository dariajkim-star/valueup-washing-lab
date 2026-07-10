"""valueup_score table

Revision ID: 0008_valueup_score
Revises: 0007_ownership
Create Date: 2026-07-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_valueup_score"
down_revision: str | None = "0007_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "valueup_score",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "corp_code",
            sa.String(length=8),
            sa.ForeignKey("company.corp_code"),
            nullable=False,
            index=True,
        ),
        sa.Column("as_of", sa.String(length=10), nullable=False),
        sa.Column("achievement_rate", sa.Float),
        sa.Column("progress_rate", sa.Float),
        sa.Column("execution_score", sa.Float),
        sa.Column("washing_flag", sa.Boolean),
        sa.Column("buyback_executed", sa.Boolean),
        sa.Column("buyback_retired", sa.Boolean),
        sa.Column("buyback_status", sa.String(length=20)),
        sa.UniqueConstraint("corp_code", "as_of", name="uq_valueup_score_corp_asof"),
    )


def downgrade() -> None:
    op.drop_table("valueup_score")
