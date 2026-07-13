"""mna_score table

Revision ID: 0009_mna_score
Revises: 0008_valueup_score
Create Date: 2026-07-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_mna_score"
down_revision: str | None = "0008_valueup_score"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mna_score",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "corp_code",
            sa.String(length=8),
            sa.ForeignKey("company.corp_code"),
            nullable=False,
            index=True,
        ),
        sa.Column("as_of", sa.String(length=10), nullable=False),
        sa.Column("mna_target_score", sa.Float),
        sa.Column("valuation_score", sa.Float),
        sa.Column("capacity_score", sa.Float),
        sa.Column("ownership_score", sa.Float),
        sa.Column("macro_score", sa.Float),
        sa.UniqueConstraint("corp_code", "as_of", name="uq_mna_score_corp_asof"),
    )


def downgrade() -> None:
    op.drop_table("mna_score")
