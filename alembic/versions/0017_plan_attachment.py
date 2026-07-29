"""plan_attachment — 첨부(PDF)에서 읽은 목표 + 페이지 단위 출처

Revision ID: 0017_plan_attachment
Revises: 0016_valueup_score_source_plan
Create Date: 2026-07-29

왜 valueup_plan에 컬럼을 더하지 않고 형제 테이블인가:
    valueup_plan은 **본문(document.xml)** 원천이고 그 upsert는 "재파싱 결과가 권위 →
    null 포함 전체 교체"다. 첨부에서 읽은 값을 같은 행에 섞으면 본문 재수집 한 번에
    첨부 파싱 결과가 통째로 날아간다. 두 원천은 수명주기가 다르므로 분리한다.
    (opacity_score를 valueup_score 컬럼이 아니라 mna_score 형제로 둔 것과 같은 판단.)

취득은 왜 자동이 아닌가:
    DART robots.txt가 뷰어·첨부·PDF 다운로드 경로를 전부 Disallow한다(2026-07-29 확인).
    그래서 파일은 사람이 받아 `attachments/`에 두고, 코드는 그 파일을 읽기만 한다.
    acquired_by/acquired_at이 그 사실을 데이터에 남긴다 — 나중에 "이건 어떻게 얻었나"를
    묻는 사람이 코드를 뒤지지 않아도 되게.

evidence_json:
    필드별 근거 페이지({"target_roe": 7, ...}). "첨부 PDF p.7"을 화면에 쓰기 위한 것이며,
    이 프로젝트가 지켜온 "값에는 출처가 따라붙는다" 원칙의 첨부판이다.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_plan_attachment"
down_revision: str | None = "0016_valueup_score_source_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plan_attachment",
        sa.Column("attachment_id", sa.Integer, primary_key=True, autoincrement=True),
        # 어느 공시의 첨부인가. plan_id로 묶으면 공시일·접수번호가 자동으로 따라온다.
        sa.Column("plan_id", sa.Integer, nullable=False, index=True),
        sa.Column("corp_code", sa.String(8), nullable=False, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        # 같은 파일을 두 번 파싱했는지, 파일이 바뀌었는지 판별(재파싱 멱등성의 기준).
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer),
        # 취득 경로를 데이터에 남긴다: 'manual'만 존재할 예정이지만 명시가 기록이다.
        sa.Column("acquired_by", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("acquired_at", sa.String(10)),  # ISO date
        sa.Column("parsed_at", sa.String(10)),
        # 파싱 결과(valueup_plan과 같은 목표 5종 + 기간)
        sa.Column("target_roe", sa.Float),
        sa.Column("target_payout_ratio", sa.Float),
        sa.Column("target_total_return_ratio", sa.Float),
        sa.Column("target_pbr", sa.Float),
        sa.Column("period_start", sa.String(10)),
        sa.Column("period_end", sa.String(10)),
        sa.Column("buyback_planned", sa.Boolean),
        # 필드 → 근거 페이지 번호(JSON 문자열). "첨부 PDF p.7"의 근거.
        sa.Column("evidence_json", sa.Text),
        # 파싱 실패를 조용히 null로 넘기지 않는다 — 왜 못 읽었는지 남긴다
        # (예: 'hwp_unsupported', 'no_text_layer'(스캔본), 'parse_error:...').
        sa.Column("parse_error", sa.String(200)),
        sa.Column("extracted_text", sa.Text),  # 원문 보존(재파싱 가능 — valueup_plan.raw_text와 같은 원칙)
        sa.UniqueConstraint("plan_id", "filename", name="uq_plan_attachment_plan_file"),
    )


def downgrade() -> None:
    op.drop_table("plan_attachment")
