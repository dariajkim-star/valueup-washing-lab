"""valuation_metrics: EBITDA 근사 폐기 → EV/EBIT·EBIT마진으로 통일 (2026-08-04)

Revision ID: 0025_metrics_view_ebit
Revises: 0024_plan_own_gap_view
Create Date: 2026-08-04

이전 정의는 `COALESCE(f.depreciation, 0)`으로 감가상각 결측을 메웠다. 그 결과 357곳 중
감가상각을 아는 58곳만 EBITDA로, 나머지 299곳(84%)은 EBIT로 재고 있었는데, M&A 점수는
그 둘을 **같은 모집단의 백분위**로 세운다 — 즉 순위가 '감가상각을 공시했다'는 사실에
가점을 주고 있었다(실측: 58곳 백분위가 전원 EBIT 대비 중앙값 6.4%p 이동, 14곳 10%p 초과).

수집으로는 못 고친다: 결측 289곳 중 무작위 30곳의 원문에 감가상각 행이 **0/30**이었다
(요약 API의 현금흐름표 행 목록이 잘려 있음 — 한전 total_debt와 같은 패턴). 그래서
근사를 유지하는 대신 **분자를 EBIT로 통일**하고 이름도 사실대로 바꾼다.

컬럼 rename(ev_ebitda→ev_ebit, ebitda_margin→ebit_margin)이라 API 응답·필터·정렬 키와
export CSV 헤더가 함께 바뀐다. 뷰는 저장 실체가 없으므로 DROP→CREATE로 갈아끼운다.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.sql_views import CREATE_VALUATION_METRICS, DROP_VALUATION_METRICS

revision: str = "0025_metrics_view_ebit"
down_revision: str | None = "0024_plan_own_gap_view"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(DROP_VALUATION_METRICS)
    op.execute(CREATE_VALUATION_METRICS)


def downgrade() -> None:
    # 이전 정의(EBITDA 근사)로 되돌리려면 그 시점 본문이 필요하다 — 뷰만 지운다.
    op.execute(DROP_VALUATION_METRICS)
