"""valuation_metrics 뷰에 total_return_ratio 추가 (5-1)

Revision ID: 0013_metrics_view_total_return
Revises: 0012_coverage_fields
Create Date: 2026-07-22

뷰는 Base.metadata 밖의 raw SQL이라(1.7 결정) 정의가 바뀌면 DROP→CREATE로 갈아끼운다.
데이터 이동은 없다 — 뷰는 저장 실체가 없으므로 재생성만으로 새 컬럼이 반영된다.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.sql_views import CREATE_VALUATION_METRICS, DROP_VALUATION_METRICS

revision: str = "0013_metrics_view_total_return"
down_revision: str | None = "0012_coverage_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(DROP_VALUATION_METRICS)
    op.execute(CREATE_VALUATION_METRICS)


def downgrade() -> None:
    # 이전 정의로 되돌리려면 0005의 본문이 필요하다 — 뷰만 지운다(재생성은 0005 재실행).
    op.execute(DROP_VALUATION_METRICS)
