"""opacity_score table

opacity_rank(공시 불투명도 순위)의 저장 테이블. mna_score의 형제 — 둘 다 cross-sectional
백분위(모집단 안의 상대 위치가 곧 점수)라 세대가 섞이면 표 자체가 무의미해진다. 그래서
washing_flag처럼 valueup_score(종목별 절대 측정치, 종목별 커밋)에 컬럼으로 얹지 않고,
mna_score와 같은 전량 원자성 테이블로 분리한다(파티 결정 2026-07-23 "저장은 mna 옆").

Revision ID: 0014_opacity_score
Revises: 0013_metrics_view_total_return
Create Date: 2026-07-23
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_opacity_score"
down_revision: str | None = "0013_metrics_view_total_return"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "opacity_score",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "corp_code",
            sa.String(length=8),
            sa.ForeignKey("company.corp_code"),
            nullable=False,
            index=True,
        ),
        sa.Column("as_of", sa.String(length=10), nullable=False),
        sa.Column("opacity_rank", sa.Float),  # peer 대비 백분위(0~1, 높을수록 불투명)
        sa.Column("opacity_count", sa.Integer),  # 미공시 축 수(0~4)
        sa.Column("opacity_basis", sa.String(length=20)),  # sector:{KSIC2}/market_fallback/market
        sa.UniqueConstraint("corp_code", "as_of", name="uq_opacity_score_corp_asof"),
    )


def downgrade() -> None:
    op.drop_table("opacity_score")
