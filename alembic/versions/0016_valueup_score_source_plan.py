"""valueup_score.source_plan_id — 이 점수가 실제로 어느 공시를 근거로 삼았는가

Revision ID: 0016_valueup_score_source_plan
Revises: 0015_valueup_plan_rcept_no
Create Date: 2026-07-29

왜 필요한가:
    0015에서 출처(공시일·접수번호)를 화면에 붙일 때, 서빙 쪽이 "최신 공시"라는 **규칙을
    다시 계산해서** 조인했다. 규칙이 엔진과 서빙 두 곳에 존재하는 구조다.

    2026-07-29 폴백 도입(최신이 0축이면 이전 공시로 내려감)으로 그 위험이 실재화됐다 —
    규칙이 조금이라도 어긋나면 화면이 **실제 채점 근거가 아닌 공시**를 출처로 표시한다.
    출처 표기의 목적이 정확히 그 반대이므로 용납할 수 없다.

    그래서 엔진이 **고른 결과 자체**를 기록한다. 서빙은 규칙을 재현하지 않고 이 id로
    조인만 한다 — 두 곳이 어긋날 여지가 사라진다.

used_fallback을 따로 두지 않는 이유:
    폴백 여부는 source_plan_id와 그 종목의 최신 공시를 비교하면 유도된다. 파생값을
    별도 컬럼으로 두면 둘이 어긋날 수 있다(같은 사실의 두 벌 저장). 화면 표기는
    서빙 시점에 "이 plan이 그 종목의 최신인가"로 판정한다.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_valueup_score_source_plan"
down_revision: str | None = "0015_valueup_plan_rcept_no"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # nullable: 기존 행은 어느 공시를 썼는지 기록이 없다(재채점해야 채워진다).
    # null = "이 점수가 어느 공시 기준인지 모른다" — 화면은 그 사실을 그대로 말해야 한다.
    # FK를 걸지 않는 이유: valueup_plan은 재수집 시 행이 갈릴 수 있고(자연키 upsert),
    # 그때 점수 행이 FK 위반으로 막히는 것보다 출처가 null이 되는 편이 안전하다.
    op.add_column("valueup_score", sa.Column("source_plan_id", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("valueup_score", "source_plan_id")
