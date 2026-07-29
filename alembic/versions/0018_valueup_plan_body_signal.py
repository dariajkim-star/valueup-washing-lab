"""valueup_plan.body_signal — 본문이 왜 우리 축을 못 채웠는가

Revision ID: 0018_valueup_plan_body_signal
Revises: 0017_plan_attachment
Create Date: 2026-07-29

2026-07-29 실측이 만든 컬럼. 그날까지 아래 셋이 전부 "미공시 4축"이라는 같은 칸에
있었는데 실제로는 서로 다른 세 가지였다:

    LG에너지솔루션  매출 2배 · EBITDA Margin 10% 중반 이상  → 다른 지표로 **공시했다**
    SK하이닉스      CapEx/Revenue 30% 중반 목표             → 위와 같은 유형
    우리금융지주    "旣공시(2026.2.6) 내용 참조"            → 다른 공시를 가리키는 재공시

구분이 없으면 두 가지를 잘못한다:
  1. 화면이 "순위 불가"라고만 말해 사용자가 '부실 공시'로 읽는다. LG엔솔은 부실하게
     공시한 게 아니라 우리 자에 그 눈금이 없는 것이다.
  2. 첨부 작업 목록이 엉뚱한 공시를 가리킨다(우리금융엔 03-23이 아니라 02-06이 필요).

body_reference_date는 refiling일 때 가리킨 공시일. 못 읽으면 null — 추측하지 않는다.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_valueup_plan_body_signal"
down_revision: str | None = "0017_plan_attachment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # nullable: 기존 행은 분류 전이다. raw_text가 보존돼 있으므로 백필로 채운다
    # (app/analysis/backfill_body_signal.py). null = "아직 분류하지 않음".
    op.add_column("valueup_plan", sa.Column("body_signal", sa.String(24), nullable=True))
    op.add_column(
        "valueup_plan", sa.Column("body_reference_date", sa.String(10), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("valueup_plan", "body_reference_date")
    op.drop_column("valueup_plan", "body_signal")
