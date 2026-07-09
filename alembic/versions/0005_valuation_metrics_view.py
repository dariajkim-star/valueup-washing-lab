"""valuation_metrics SQL VIEW

Revision ID: 0005_valuation_metrics_view
Revises: 0004_macro
Create Date: 2026-07-08
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.sql_views import CREATE_VALUATION_METRICS, DROP_VALUATION_METRICS

revision: str = "0005_valuation_metrics_view"
down_revision: str | None = "0004_macro"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(CREATE_VALUATION_METRICS)


def downgrade() -> None:
    op.execute(DROP_VALUATION_METRICS)
