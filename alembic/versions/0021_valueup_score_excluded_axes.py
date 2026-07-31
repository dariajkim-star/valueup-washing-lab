"""채점에서 제외된 축과 그 사유 — '못 잰 축'이 조용히 사라지지 않게

Revision ID: 0021_valueup_score_excluded_axes
Revises: 0020_attachment_ocr_review
Create Date: 2026-07-31

■ 무엇이 문제였나
    계획 기간(period_start)이 없으면 progress_rate가 null이고, gap_engine은 그때
    achievement_rate도 null로 둔다(AC3 — 진척을 모르면 '진척 대비 달성'을 말할 수 없다.
    이 게이팅 자체는 옳다). 그런데 ROE 목표를 공시한 기업은 _execution_score에서
    "약속했는데 실적 미상 → 판단 불가"로 걸려 **전체 점수가 null**이 됐다.

    실측(표본 359, as_of 2026-07-13): 채점 실패 264행 중 **235행이 계획 기간 없음**이고,
    그중 **75행은 환원·자사주 축을 실제로 잴 수 있는데도** 점수가 통째로 죽었다.
    예) 엘지이노텍 — 목표 ROE 15.0·배당성향 20.0, 실적 ROE 8.39·배당성향 11.01.
    둘 다 잴 수 있으나 계획 기간이 없어 execution_score = null.

    이는 2026-07-23 교차리뷰 ⑥에서 고친 결함과 같은 계열이다. 그때는 "한 축의 미달이
    다른 축의 이행을 상쇄"였고, 지금은 "한 축의 **측정 불가**가 다른 축의 측정 가능을
    지운다". 원칙은 같다 — 미달도 미상도 그 축의 문제지 다른 축을 무효화하지 않는다.

■ 무엇을 바꾸나
    기간이 무효면 ROE 축을 **채점에서 제외**하고 나머지 축으로 채점한다. 대신 제외했다는
    사실을 이 컬럼에 남긴다 — score_basis에서 빠지는 것만으로는 부족하다. 화면이
    "ROE는 계획 기간 미상으로 채점 제외"라고 말할 수 있어야 한다(Grumbal: "조용히
    사라지면 그게 세탁이다").

excluded_axes:
    "축:사유" 목록, 쉼표 구분. 현재 유일한 값은 "roe:no_period".
    null = 제외된 축 없음. score_basis(포함된 축)의 여집합 기록이다.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_valueup_score_excluded_axes"
down_revision: str | None = "0020_attachment_ocr_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "valueup_score", sa.Column("excluded_axes", sa.String(100), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("valueup_score", "excluded_axes")
