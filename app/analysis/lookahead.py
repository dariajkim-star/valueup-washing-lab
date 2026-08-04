"""look-ahead 차단 규칙의 **단일 정의처** (2026-08-04, 마이그 0029).

이 규칙은 그동안 5곳에 복제돼 있었다(screening·mna_score·valueup_score·export×2).
복제된 규칙은 갈라진다 — 이 프로젝트가 `plan_own_gap`(0024)·`plan_selection`(0016)에서
반복해 배운 실패이고, 실제로 mna_score 주석과 export 주석의 서술이 이미 미세하게
달라져 있었다. 규칙을 여기 한 곳에 두고 나머지는 이것을 부른다.

■ 무엇을 막는가
`as_of` 시점에 **아직 공시되지 않은 재무**가 지표에 섞이는 것. 과거 시점을 재현해
"그때 이 화면은 무엇을 보여줬을까"를 물을 수 있어야 하는데, 미래 데이터가 섞이면
그 답이 거짓말이 된다.

■ 규칙 (0029에서 사실 기반으로 승격)
1. `available_at`(사업보고서 rcept_dt)을 **아는 행은 그 날짜로 판정**한다 —
   `available_at <= as_of`.
2. **모르는 행(null)은 연도 휴리스틱으로 폴백**한다 —
   `year < as_of_year OR (year = as_of_year AND quarter < 4)`.
   수집 못 한 행을 통째로 떨구면 "모른다"가 "없다"가 된다(NFR2).

■ 왜 휴리스틱만으로는 부족했나 (2026-08-04 재측정)
휴리스틱은 `year < as_of_year`이면 무조건 통과시킨다. 그런데 실측하면 기아의 2024
사업보고서는 **2025-03-06** 공시다. `as_of = 2025-01-15`로 조회하면 아직 공시되지도
않은 2024 재무가 들어간다 — **연도가 과거라는 사실이 공시됐다는 뜻은 아니다.**

■ 정정된 진단 (문서화된 서술이 틀렸었다)
코드 주석·백로그·API 문서는 잔여 위험을 *"1~3분기 보고서의 동일연도 시차"*로 적어왔다.
그러나 financials는 **전량 quarter=4**다(2023년 349행·2024년 357행). 그 집합은 비어 있고,
실제 잔여는 **사업보고서 자체의 공시 시차**였다. 착수 전 재측정이 아니었으면 빈 곳을
막을 뻔했다.
"""

from __future__ import annotations

from typing import Any

# SQL 조건절. `:as_of`(YYYY-MM-DD)와 `:as_of_year`(INT) 두 바인드를 요구한다.
# 테이블 별칭이 필요한 소비자를 위해 prefix를 받는다("f." 등, 없으면 빈 문자열).
_SQL_TEMPLATE = (
    "({p}available_at IS NOT NULL AND {p}available_at <= :as_of) "
    "OR ({p}available_at IS NULL AND "
    "({p}year < :as_of_year OR ({p}year = :as_of_year AND {p}quarter < 4)))"
)


def sql_where(prefix: str = "") -> str:
    """look-ahead 통과 조건의 SQL 조각. 괄호로 감싸여 있으므로 AND/OR로 이어 붙일 수 있다.

    prefix는 테이블 별칭("f." 등). 바인드 파라미터는 `params()`가 만든다.
    """
    return "(" + _SQL_TEMPLATE.format(p=prefix) + ")"


def params(as_of: str) -> dict[str, Any]:
    """`sql_where`가 요구하는 바인드 값. as_of는 'YYYY-MM-DD'."""
    return {"as_of": as_of, "as_of_year": int(as_of[:4])}


def is_available(
    available_at: str | None, year: int, quarter: int, as_of: str
) -> bool:
    """같은 규칙의 파이썬 판. ORM 경로(valueup_score)와 테스트가 쓴다.

    SQL과 파이썬 두 벌이 되지만 **정의는 이 파일 하나**이며, 두 판이 같은 답을
    내는지는 `tests/test_lookahead.py`가 대조로 강제한다(plan_own_gap 이관 때와 같은 방식).
    """
    if available_at is not None:
        return available_at <= as_of
    as_of_year = int(as_of[:4])
    return year < as_of_year or (year == as_of_year and quarter < 4)
