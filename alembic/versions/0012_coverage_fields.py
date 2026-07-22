"""주주환원율 목표 + score_basis (5-1 execution_score 커버리지)

Revision ID: 0012_coverage_fields
Revises: 0011_valueup_score_gap_fields
Create Date: 2026-07-22
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_coverage_fields"
down_revision: str | None = "0011_valueup_score_gap_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 배당성향과 다른 지표라 별도 컬럼(기존 값을 옮기지 않는다 — 섞으면 정의가 어긋난다)
    op.add_column("valueup_plan", sa.Column("target_total_return_ratio", sa.Float))
    op.add_column("valueup_score", sa.Column("score_basis", sa.String(40)))


def downgrade() -> None:
    op.drop_column("valueup_score", "score_basis")
    op.drop_column("valueup_plan", "target_total_return_ratio")
