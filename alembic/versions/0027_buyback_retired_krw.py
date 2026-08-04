"""financials.buyback_retired_krw 추가 — 소각 '금액' 수집 (2026-08-04 2차)

Revision ID: 0027_buyback_retired_krw
Revises: 0026_buyback_amount_krw
Create Date: 2026-08-04

소각은 수량(주)만 있었다(buyback_retired_amount). 금액이 없어서 "매입 1,004억 ·
소각 ?"처럼 취득 금액(0026)과 같은 축에서 만나지 못했다 — 환원율을 소각 기준으로
재론하는 전제가 이 열이다.

재측정(표본 20)이 백로그 원안("CF에서 캐자")을 뒤집었다 — **소각은 비현금 사건이라
CF에 없는 게 회계적으로 당연**했다. CF에서 보이는 것은 소각 '비용'(수수료)뿐이다.
실체는 **SCE(자본변동표)**: 태그 `ifrs-full_CancellationOfTreasuryShares`가 지배적
(HIT 16/20 중 13, 이름 변형은 '자기주식 소각'·'자기주식의 소각'·'자기주식소각').
0026 취득액과 정반대로 **이 열은 태그가 권위다** — 열마다 권위가 다르다는 어제
문장의 세 번째 사례.

MISS 4(우리금융 '자기주식 순증감'·콜마 '취득 및 처분'·현대모비스 '변동')는 소각이
다른 사건과 **한 행에 섞여 분해 불가** — null이 정답(0026의 '금융부채' 총액형과 동일).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_buyback_retired_krw"
down_revision: str | None = "0026_buyback_amount_krw"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "financials", sa.Column("buyback_retired_krw", sa.BigInteger(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("financials", "buyback_retired_krw")
