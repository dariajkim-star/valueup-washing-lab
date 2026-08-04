"""financials.buyback_amount_krw 추가 + total_return_ratio 단위 정정 (2026-08-04)

Revision ID: 0026_buyback_amount_krw
Revises: 0025_metrics_view_ebit
Create Date: 2026-08-04

total_return_ratio 뷰가 (dividend_total + buyback_amount)를 쓰는데, buyback_amount는
**자사주 취득 수량(주)**이고 dividend_total은 **원**이다. 원에 주식 수를 더하고 있었다.

실측: 산출된 579행 중 564행에서 total_return_ratio가 payout_ratio와 소수 둘째자리까지
동일했고, 자사주 1,445만 주를 매입한 종목조차 기여가 0.01%p였다. 즉 이 축은 배당성향의
복제였고, 자사주로 환원한 기업을 미이행처럼 보이게 했다(false negative).

금액의 원천은 tesstkAcqsDspsSttus가 아니라 **재무제표 현금흐름표**다(그 표에는 수량 칸만
있다 — bsis_qy·change_qy_*·trmend_qy). 수량 열은 자사주 0 게이트가 쓰므로 보존하고,
금액은 새 열로 추가한다(대체 아님). 열 이름에 단위를 박는다.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.sql_views import CREATE_VALUATION_METRICS, DROP_VALUATION_METRICS

revision: str = "0026_buyback_amount_krw"
down_revision: str | None = "0025_metrics_view_ebit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("financials", sa.Column("buyback_amount_krw", sa.BigInteger(), nullable=True))
    op.execute(DROP_VALUATION_METRICS)
    op.execute(CREATE_VALUATION_METRICS)


def downgrade() -> None:
    op.execute(DROP_VALUATION_METRICS)
    op.drop_column("financials", "buyback_amount_krw")
