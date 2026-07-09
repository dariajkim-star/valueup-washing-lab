"""baseline (빈 초기 리비전)

이 스토리(1.1)는 마이그레이션 환경만 확립한다. 테이블은 후속 스토리에서 추가.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-08
"""
from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 빈 baseline. 테이블은 후속 스토리(1.2~)에서 추가된다.
    pass


def downgrade() -> None:
    pass
