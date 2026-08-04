"""valuation_metrics에 소각 기준 두 파생 추가 — retired_return_ratio·retirement_rate

Revision ID: 0028_retired_return_metrics
Revises: 0027_buyback_retired_krw
Create Date: 2026-08-04

0027이 소각 '금액'을 채워 백로그("소각하지 않은 자사주를 환원으로 볼 것인가")를
다시 열었다. 정의를 바꾸지 않는다 — total_return_ratio(매입 기준, 업계 표준)는
그대로 두고 **소각 기준 시선을 나란히** 추가한다(scoring.md 의도된 이중 시선의
수치화). 두 값의 차이가 곧 '매입만 한 기업' 신호다.

- retired_return_ratio = (배당 + 소각액)/순이익
- retirement_rate = 소각액/취득액(동일 회계연도, 이월 소각으로 100% 초과 가능 — 캡 없음)
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.sql_views import CREATE_VALUATION_METRICS, DROP_VALUATION_METRICS

revision: str = "0028_retired_return_metrics"
down_revision: str | None = "0027_buyback_retired_krw"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(DROP_VALUATION_METRICS)
    op.execute(CREATE_VALUATION_METRICS)


def downgrade() -> None:
    # 뷰 정의는 sql_views.py 단일 원천이라 구버전 SQL을 복제하지 않는다 —
    # 코드 체크아웃을 되돌린 상태에서 upgrade와 동일하게 재생성하는 것이 계약.
    op.execute(DROP_VALUATION_METRICS)
    op.execute(CREATE_VALUATION_METRICS)
