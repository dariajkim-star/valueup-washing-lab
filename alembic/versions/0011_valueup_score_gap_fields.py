"""valueup_score target/actual/gap 동결 컬럼 (2.4 갭분석 API)

Revision ID: 0011_valueup_score_gap_fields
Revises: 0010_mna_population_basis
Create Date: 2026-07-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_valueup_score_gap_fields"
down_revision: str | None = "0010_mna_population_basis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("valueup_score", sa.Column("target_roe", sa.Float))
    op.add_column("valueup_score", sa.Column("actual_roe", sa.Float))
    op.add_column("valueup_score", sa.Column("roe_gap", sa.Float))


def downgrade() -> None:
    op.drop_column("valueup_score", "roe_gap")
    op.drop_column("valueup_score", "actual_roe")
    op.drop_column("valueup_score", "target_roe")
