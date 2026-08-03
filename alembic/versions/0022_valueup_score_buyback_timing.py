"""소각이 **약속 전인가 후인가** — buyback_status가 답하지 못하던 질문

Revision ID: 0022_valueup_score_buyback_timing
Revises: 0021_valueup_score_excluded_axes
Create Date: 2026-07-31

■ 문제
    `buyback_status='retired'`는 "직전 재무기간에 소각이 있었다"는 사실만 말한다. 밸류업
    계획과 무관하므로 화면 라벨도 "소각 이행"이 아니라 "최근 소각"으로 정정해 두었다
    (2026-07-28). 그러나 **약속 이행을 재는 지표는 여전히 없었다**(백로그 P1-4).

    원안은 계획 기간(period_start~period_end)으로 재는 것이었는데, 실측상 `retired` 53건 중
    기간을 아는 건 16건(30%)뿐이라 70%가 미상으로 남는다. P1-8(기간 파싱)을 개선한 뒤에도
    25% → 30%에 그쳤다 — 기간이 문서에 없기 때문이다.

■ 재설계 (2026-07-31 리드 결정)
    `disclosure_date`는 전건 보유한다. "약속한 **기간에** 했나" 대신 "약속한 **뒤에** 했나"를
    물으면 판정 가능률이 크게 오른다. 두 기준을 배타적으로 쓰지 않고, 기간을 아는 건은
    더 엄밀한 기간 기준으로, 나머지는 공시일 기준으로 재되 **어느 자로 쟀는지 값 자체가
    말하게** 한다(score_basis·population_basis와 같은 패턴).

■ 값 (self-describing — basis를 별도 컬럼으로 두지 않는다)
    in_period          계획 기간 안에서 소각 (기간 기준)
    outside_period     계획 기간 밖에서 소각 (기간 기준)
    after_disclosure   공시 연도보다 뒤 회계연도에 소각 (공시일 기준)
    before_disclosure  공시 연도보다 앞 회계연도에 소각 (공시일 기준)
    same_year_unknown  공시와 **같은 해** — 분기 정보로는 전후를 가릴 수 없다(판정 불가)
    null               소각 자체가 없음(retired 아님) 또는 근거 부족

■ same_year_unknown을 따로 둔 이유
    연도 단위 비교라 "2026-03 공시 / FY2026 소각"은 3월 전후를 알 수 없다. 느슨하게
    "이후"로 처리하면 **12건이 이행으로 잘못 표시**된다(실측). null > 틀린 값(NFR2).

■ 실측 결과(as_of 2026-07-13, retired 53건)
    기간 내 5 · 기간 밖 11 · 공시 이후 0 · 공시 이전 30 · 같은 해 7 → 판정 가능 46 (87%)
    → "최근 소각" 53건 중 **약속 후 이행이 확인되는 것은 5건뿐**이다.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_valueup_score_buyback_timing"
down_revision: str | None = "0021_valueup_score_excluded_axes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "valueup_score", sa.Column("buyback_timing", sa.String(20), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("valueup_score", "buyback_timing")
