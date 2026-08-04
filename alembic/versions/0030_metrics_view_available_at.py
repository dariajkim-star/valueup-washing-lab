"""valuation_metrics에 available_at 노출 — look-ahead 게이트가 뷰를 읽는다 (2026-08-04)

Revision ID: 0030_metrics_view_available_at
Revises: 0029_financials_available_at
Create Date: 2026-08-04

지표 조회 경로(screening·mna_score·export)는 financials가 아니라 valuation_metrics를
읽는다. 0029가 심은 `available_at`을 게이트가 쓰려면 뷰가 그 열을 통과시켜야 한다.
계산 열은 하나도 바뀌지 않는다 — 통과 열 하나 추가뿐이다.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.sql_views import CREATE_VALUATION_METRICS, DROP_VALUATION_METRICS

revision: str = "0030_metrics_view_available_at"
down_revision: str | None = "0029_financials_available_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(DROP_VALUATION_METRICS)
    op.execute(CREATE_VALUATION_METRICS)


def downgrade() -> None:
    # 뷰 정의는 sql_views.py 단일 원천 — 구버전 SQL을 복제하지 않는다(0028과 동일 계약)
    op.execute(DROP_VALUATION_METRICS)
    op.execute(CREATE_VALUATION_METRICS)
