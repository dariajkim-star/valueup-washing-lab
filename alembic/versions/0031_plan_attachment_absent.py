"""valueup_plan.attachment_absent 추가 — '받으러 갈 문서가 존재하나' (2026-08-05)

Revision ID: 0031_plan_attachment_absent
Revises: 0030_metrics_view_available_at
Create Date: 2026-08-05

**전날의 칸 선택을 재측정이 정정한다.** 2026-08-04에 첨부 부존재 선언을
`body_signal='exempt_short_form'`으로 담았는데, 다음날 전 코퍼스를 세어보니 선언한
공시는 101개사가 아니라 **212건**이고 그중 102건만 그 신호를 달고 있었다:

    axis_targets        102   ← 축까지 공시한 회사도 첨부는 안 붙였다
    exempt_short_form   102
    other_metric          6   ← 첨부 작업 목록이 여전히 부르고 있었다
    refiling              2   ← 〃 (신도리코)

`classify_body`는 우선순위 사다리이고 exempt는 맨 아래 칸이었다. 목표를 어떤 형태로든
공시한 회사가 첨부 부존재를 함께 선언하면 위쪽 신호에 가려 샌다. 그 결과 어제 고친
결함(존재하지 않는 문서를 찾아오라는 작업 목록)이 **7건 남아 있었다.**

우선순위만 올리는 처방은 더 나쁘다 — `refiling`은 **선택 규칙**을 바꾸는 신호라
(가리킨 공시로 이동) exempt로 덮으면 신도리코가 가리킨 실제 계획을 못 따라간다.

두 사실은 경쟁하지 않고 **서로 다른 질문에 답한다**:

    body_signal        "이 본문이 왜 우리 4축을 못 채웠나"   → 화면 문구·선택 규칙
    attachment_absent  "받으러 갈 문서가 존재하나"            → 첨부 작업 목록

그래서 직교 컬럼으로 옮긴다. `exempt_short_form` 값은 백필이 `no_targets`로 되돌린다
(둘을 겹쳐 두면 같은 사실이 두 곳에 살고, 그게 갈라지는 시작이다).

nullable인 이유(NFR2): null은 "첨부가 있다"가 아니라 **"아직 판정하지 않았다"**이다.
원문이 없으면 선언 여부를 알 수 없고, 모르는 것을 False로 굳히면 워크리스트가 다시
거짓을 말하게 된다.

점수 영향 0 — 이 컬럼은 채점 경로에 들어가지 않는다(작업 목록과 상세 화면 문구만).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_plan_attachment_absent"
down_revision: str | None = "0030_metrics_view_available_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "valueup_plan", sa.Column("attachment_absent", sa.Boolean(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("valueup_plan", "attachment_absent")
