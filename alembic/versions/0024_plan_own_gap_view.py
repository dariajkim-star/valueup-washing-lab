"""plan_own_gap 뷰 신설 — 목표의 야심도(자기 과거 기준선)를 목록에서도 쓰기 (P1-7)

Revision ID: 0024_plan_own_gap_view
Revises: 0023_valueup_plan_target_ranges
Create Date: 2026-08-03

야심도는 지금까지 상세(단건)에서 서빙 시점에만 계산됐다. 목록에서 필터·정렬을 하려면
SQL이 그 값을 알아야 하는데, 파이썬과 SQL에 계산을 각각 두면 두 정의가 갈라진다.
그래서 **뷰를 단일 정의처로 두고 `_ambition`이 이것을 읽는다**.

저장 실체가 없다 — 파생 컬럼도, as_of마다 채워야 할 백필도 만들지 않는다(P1-7이
"as_of마다 다시 채워야 하는 파생값이 하나 더 는다"며 저장을 피한 판단을 그대로 지킨다).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.sql_views import CREATE_PLAN_OWN_GAP, DROP_PLAN_OWN_GAP

revision: str = "0024_plan_own_gap_view"
down_revision: str | None = "0023_valueup_plan_target_ranges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(DROP_PLAN_OWN_GAP)  # 멱등: 부분 적용 상태에서 재실행 가능
    op.execute(CREATE_PLAN_OWN_GAP)


def downgrade() -> None:
    op.execute(DROP_PLAN_OWN_GAP)
