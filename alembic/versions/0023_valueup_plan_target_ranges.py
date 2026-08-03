"""범위로 공시한 목표 — 하한을 채택하되 원문 범위를 남긴다

Revision ID: 0023_valueup_plan_target_ranges
Revises: 0022_valueup_score_buyback_timing
Create Date: 2026-07-31

■ 무엇이 문제였나
    `_plain_gap`은 라벨-값 사이에 숫자를 허용하지 않는다(경쟁 지표의 %를 훔쳐오는 오탐
    차단 — 일괄리뷰 High). 그 규칙 때문에 "ROE 11~13%"는 **범위의 앞 숫자에서 매칭이
    끊겨** 통째로 버려졌다.

    실측(2026-07-31, 표본 359): ROE 24건 중 22건 · 주주환원율 8건 전부 · 배당성향 6건 중
    5건 — 합계 **35건**이 사라지고 있었다. 삼성화재 "ROE 11~13%", "2030년까지 연결
    ROE 13~15%"처럼 **명확하게 공시된** 목표들이다.

■ 왜 하한인가 (리드 결정 2026-07-31)
    범위로 약속했다면 회사가 **확실히 약속한 것은 하한**이다. 중앙값은 공시에 없는 숫자를
    우리가 만드는 것이라 "억지 추정 금지"(SM-C1)와 어긋나고, 상한은 회사가 하지 않은
    약속으로 판정하는 셈이다.

■ 왜 컬럼이 필요한가
    하한만 저장하면 "11~13%로 약속한 회사"와 "11%로 약속한 회사"가 화면에서 같아 보인다.
    전자는 달성 판정이 관대해진 상태이므로, 그 사실을 감추면 안 된다.
    이 프로젝트가 지켜온 계약("값에는 출처가 따라붙는다" — score_basis·population_basis·
    plan_disclosure_date·excluded_axes)의 연장이다.

target_ranges:
    "축:하한~상한" 목록, 쉼표 구분. 예) "roe:11~13,payout_ratio:30~40"
    null = 범위 표현이 없었다(단일 값으로 공시).

■ P1-2에 대한 정정
    백로그의 원래 접근은 "수동 태깅 보완 레이어"였다. 그러나 실측 결과 `no_targets`
    177건 중 목표스러운 표현이 있는 건 **3건(2%)**뿐이다 — 나머지 174건은 본문에 정말
    목표가 없다(본문 길이 중앙 1,967자의 짧은 통지문). 수동 태깅으로 회수할 것이 거의
    없고, 대신 범위 파싱이 35건을 되살린다.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_valueup_plan_target_ranges"
down_revision: str | None = "0022_valueup_score_buyback_timing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "valueup_plan", sa.Column("target_ranges", sa.String(200), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("valueup_plan", "target_ranges")
