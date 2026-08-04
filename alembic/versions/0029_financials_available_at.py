"""financials.available_at 추가 — 그 재무를 '언제부터 알 수 있었나' (2026-08-04)

Revision ID: 0029_financials_available_at
Revises: 0028_retired_return_metrics
Create Date: 2026-08-04

look-ahead 차단의 마지막 구멍을 닫는다. 지금까지의 규칙은 **연도 휴리스틱**이었다 —
`year < as_of_year OR (year = as_of_year AND quarter < 4)`. "같은 해 사업보고서는 그 해
안에 공시될 수 없다(통상 다음해 3월)"는 상식에 기댄 것이다.

**착수 전 재측정이 문서화된 진단을 정정했다.** 코드 주석·백로그·API 문서는 잔여 위험을
*"1~3분기 보고서의 동일연도 시차"*로 적어왔는데, **financials에 분기 행이 하나도 없다**
(전량 quarter=4, 2023년 349행·2024년 357행). 그 집합은 비어 있다.

**실제 잔여 위험은 다른 곳에 있다 — 사업보고서 자체의 공시 시차다.**
연도 휴리스틱은 `year < as_of_year`이면 무조건 통과시키는데, 실측하면 기아의 2024
사업보고서는 **2025-03-06** 공시다. 즉 `as_of = 2025-01-15`로 조회하면 **아직 공시되지도
않은 2024 재무가 지표에 들어간다.** 연도가 과거라는 사실이 공시됐다는 뜻은 아니다.

현재 노출은 0이다(as_of가 2026-07-13 하나뿐이고 데이터는 2023~2024). 그러나
**"지금 안 터진다"와 "구조적으로 못 터진다"는 다르다** — 과거 시점 재현이 이 도구의
용도에 들어 있는 이상, 휴리스틱을 사실로 바꾼다.

`available_at`은 DART 공시검색(list.json)의 **사업보고서 rcept_dt**다. null이면 미수집
이므로 **기존 연도 휴리스틱으로 폴백**한다 — 수집 못 한 행을 조회에서 통째로 떨구면
"모른다"가 "없다"가 된다(NFR2).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_financials_available_at"
down_revision: str | None = "0028_retired_return_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "financials", sa.Column("available_at", sa.String(length=10), nullable=True)
    )
    op.add_column(
        "financials", sa.Column("available_rcept_no", sa.String(length=20), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("financials", "available_rcept_no")
    op.drop_column("financials", "available_at")
