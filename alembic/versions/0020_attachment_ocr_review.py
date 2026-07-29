"""첨부 OCR 층 — OCR 유래 값은 후보이며, 사람이 승인해야 채점에 들어간다

Revision ID: 0020_attachment_ocr_review
Revises: 0019_ir_source_url
Create Date: 2026-07-29

이미지 기반 PDF(우리금융 실측: 9쪽 중 전 페이지, native 텍스트 156자)는 OCR 없이는
기계가 못 읽는다. OCR을 붙이되 **자동 입력기가 아니라 근거 보존형 후보 추출기**로 쓴다:

  OCR = 증거를 읽는 수집층 / 검증 규칙 = 후보 판정층 / 수동 검토 = 예외 처리층

첫 실측(우리금융 스파이크)이 이 구조의 필요를 바로 증명했다 — OCR+파서가 ROE 10.0을
맞히면서 동시에 2025 이행 실적(배당성향 35.0)을 목표로 오인했다. 틀린 non-null은
null보다 위험하므로, OCR 유래 값은 needs_review=True로 적재되고 merge_attachment가
채점에 태우지 않는다. 사람이 승인·수정·기각(review_attachment CLI)해야 풀린다.

plan_attachment 추가 컬럼:
    ocr_pages     — OCR을 적용한 페이지 목록(JSON). 페이지별 extraction method의 기록.
                    evidence_json과 대조하면 어떤 값이 OCR 유래인지 재구성된다.
    needs_review  — OCR 유래 목표가 하나라도 있으면 True. 채점 반영의 게이트.
    reviewed_by / reviewed_at / review_note — 승인 기록. "값에는 출처가 따라붙는다"의
                    연장: 사람의 판정도 출처다.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_attachment_ocr_review"
down_revision: str | None = "0019_ir_source_url"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plan_attachment", sa.Column("ocr_pages", sa.Text(), nullable=True))
    op.add_column(
        "plan_attachment",
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("plan_attachment", sa.Column("reviewed_by", sa.String(50), nullable=True))
    op.add_column("plan_attachment", sa.Column("reviewed_at", sa.String(10), nullable=True))
    op.add_column("plan_attachment", sa.Column("review_note", sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column("plan_attachment", "review_note")
    op.drop_column("plan_attachment", "reviewed_at")
    op.drop_column("plan_attachment", "reviewed_by")
    op.drop_column("plan_attachment", "needs_review")
    op.drop_column("plan_attachment", "ocr_pages")
