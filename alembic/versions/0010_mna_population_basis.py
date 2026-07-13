"""mna_score.population_basis (2.7 sector peer-group)

Revision ID: 0010_mna_population_basis
Revises: 0009_mna_score
Create Date: 2026-07-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_mna_population_basis"
down_revision: str | None = "0009_mna_score"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mna_score", sa.Column("population_basis", sa.String(length=20)))


def downgrade() -> None:
    op.drop_column("mna_score", "population_basis")
