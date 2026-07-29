"""valueup_plan.rcept_no — 공시 접수번호(출처 추적의 최소 단위)

Revision ID: 0015_valueup_plan_rcept_no
Revises: 0014_opacity_score
Create Date: 2026-07-29

왜 필요한가(2026-07-29 실측):
    수집기는 list.json에서 rcept_no를 받아 document.xml을 부를 때 쓰고 **버렸다**
    (`dart_valueup.py`). 그 결과 DB에는 "어느 접수건에서 나온 값인가"가 남지 않는다.

    이것이 첨부(PDF/HWP) 수집 파이프라인의 1차 관문이다 — DART 뷰어/첨부 목록 URL은
    접수번호로 조립되므로, rcept_no가 없으면 첨부로 가는 문 자체가 없다.
    (SK하이닉스 실측: document.xml ZIP에 통지문 .xml 하나뿐, 첨부 실마리 0개.)

    스크래핑 착수 여부와 무관하게 필요하다: 목표 하나하나의 출처를 "첨부 PDF p.○"로
    기록하려면 먼저 "어느 공시인가"가 있어야 한다.

nullable인 이유:
    기존 행은 rcept_no 없이 적재됐고, 되살릴 방법은 DART 재수집뿐이다. NOT NULL로 두면
    마이그레이션이 기존 데이터를 못 받는다. **null = "아직 재수집 안 된 과거 적재분"**
    이라는 뜻이며, 이 프로젝트의 null 계약("모르는 것은 모른다고 말한다")과 일치한다.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_valueup_plan_rcept_no"
down_revision: str | None = "0014_opacity_score"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # DART 접수번호는 14자리 숫자 문자열(YYYYMMDD + 6자리 일련). 선행 0이 있으므로
    # 정수형 금지 — corp_code에서 이미 겪은 함정(선행 0 소실)과 같은 계열.
    op.add_column("valueup_plan", sa.Column("rcept_no", sa.String(14), nullable=True))
    # 접수번호로 역조회(어느 공시에서 온 값인가 → 그 공시의 모든 파생값)를 하게 되므로 인덱스.
    op.create_index("ix_valueup_plan_rcept_no", "valueup_plan", ["rcept_no"])


def downgrade() -> None:
    op.drop_index("ix_valueup_plan_rcept_no", table_name="valueup_plan")
    op.drop_column("valueup_plan", "rcept_no")
