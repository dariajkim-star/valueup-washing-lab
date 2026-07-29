"""공시가 가리킨 IR 웹페이지 URL + 첨부의 취득 출처

Revision ID: 0019_ir_source_url
Revises: 0018_valueup_plan_body_signal
Create Date: 2026-07-29

DART 첨부 경로가 닫힌 뒤(robots.txt Disallow + 실물 부재 실증) 남은 길은 공시가 스스로
가리킨 회사 IR 페이지다. 그 URL은 공시 본문의 '관련 웹페이지' 필드에 있고 raw_text에
보존돼 있으므로, 재수집 없이 뽑아 저장할 수 있다.

실측(2026-07-29): 49/60 공시가 URL을 담고 있고, 그중 LG화학은 **계획서 PDF 직링크**다.
그 PDF를 받아 파싱한 결과 ROE 10.0%(p.12)·배당성향 20.0%(p.12)를 얻었다 — 본문 폴백으로는
1축이던 종목이 2축이 됐다.

plan_attachment.source_url:
    파일을 어디서 얻었는지. acquired_by가 'manual'/'ir_site'를 구분하고, 이 컬럼이
    ir_site일 때의 정확한 출처를 남긴다. "값에는 출처가 따라붙는다"의 연장이며,
    같은 파일을 다시 받을 때 어디로 가야 하는지도 여기 있다.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_ir_source_url"
down_revision: str | None = "0018_valueup_plan_body_signal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("valueup_plan", sa.Column("related_url", sa.String(500), nullable=True))
    op.add_column("plan_attachment", sa.Column("source_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("plan_attachment", "source_url")
    op.drop_column("valueup_plan", "related_url")
