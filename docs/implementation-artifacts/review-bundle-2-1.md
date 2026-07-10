# 코드 리뷰 요청 — 밸류업 워싱 스크리너 Story 2.1 (Value-up 갭 스코어링 엔진, gap_engine)

너는 엄격한(adversarial) 시니어 코드 리뷰어야. 아래 스토리/AC, 아키텍처 제약, **전체 코드(verbatim, 축약 없음)**를 보고
버그·규약 위반·엣지케이스·null 전파 정확성 문제를 찾아줘.
출력: `[High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정`. 칭찬 생략, 없으면 "clean".

**이번 핵심 = "null vs 0" 3치 논리(tri-state)의 정확성 + 시간 정렬(look-ahead 방지) + 산식 충실도**라 특히:
- `_washing_flag`가 "입력 하나라도 None → 전체 None"인데, 이게 진짜 안전한 근사인지, 아니면 켤린(Kleene) 3치 논리(예: `buyback_retired=True`가 확정이면 나머지 몰라도 washing은 확정 False)를 놓쳐서 불필요하게 과도한 None을 뱉는지
- `latest_metrics`/`latest_financial_buyback`이 `year <= as_of_year`로만 필터하는데, **분기(quarter)까지 고려한 진짜 look-ahead 방지**가 되는지(같은 연도 내 미래 분기 데이터를 끌어올 여지)
- `latest_valueup_plan`이 `disclosure_date <= as_of` 문자열 비교인데, `as_of`가 날짜(YYYY-MM-DD)이고 `disclosure_date`도 날짜라 사전식 비교가 실제 날짜 비교와 일치하는지, 그리고 `as_of`가 다른 포맷으로 들어오면 어떻게 깨지는지
- `_progress_rate`/achievement_rate/execution_score가 scoring.md 산식과 1:1로 맞는지(가중치 곱 순서, clamp 위치, min() 캡 위치)
- `run()`이 plan 없는 corp는 스킵하는데, **이전에 스코어가 있었다가 plan이 사라진 경우**(예: 데이터 정정으로 valueup_plan 삭제) 오래된 valueup_score 행이 고아로 남는지
- upsert가 "null 포함 전체 교체"인데, 이게 정말 의도대로 동작하는지(None 값도 setattr되는지 vs upsert_financial의 "None-safe 부분갱신"과 반대 정책인데 정책 차이가 문서화·의도적인지)

## 스토리 & AC (verbatim)

- As a 애널리스트, 계획 대비 달성률·진척률·실행점수가 산출되는 것 — 밸류업 이행 정도를 종목 간 비교.
- **AC1**: `gap_engine.run(session, as_of, corp_codes=None)` 실행 시 `valueup_score`(achievement_rate, progress_rate, execution_score, buyback_executed, buyback_retired, buyback_status)가 적재(gap_engine 유일 writer, AD-4).
- **AC2**: `achievement_rate = actual_roe / target_roe`(target_roe는 as_of 시점 유효 valueup_plan, actual_roe는 as_of 이전 최신 valuation_metrics.roe), target_roe<=0이면 null.
- **AC3**: `progress_rate = clamp((as_of연도-period_start)/(period_end-period_start), 0, 1)` 연도 단위. period_start/end null이거나 end<=start면 progress_rate·achievement_rate·washing 전체 null.
- **AC4**: buyback_executed=(amount>0, null이면 null), buyback_retired=(retired_amount==0→False, >0→True, null→null), buyback_status는 retired/purchased_only/none/**unknown**(취득·소각 중 하나라도 null) 4분류.
- **AC5**: execution_score 산식(가중치는 config 주입), 세 항 중 하나라도 계산불가면 0 아니라 전체 null.
- **AC6**: washing_flag 산식, 입력 중 하나라도 null이면 washing_flag도 null(False 강제 금지).
- **AC7**: 동일 (corp_code, as_of) 재실행 시 멱등 upsert.
- **AC8**: fixture 테스트로 전부 검증, 기존 100 테스트 회귀 0.

**리드 확정 결정 3건**: (1) 다중 공시 시 as_of 이전 최신 공시 채택(단순 규칙, 기간-포함 판정 안 함). (2) target_pbr은 계산에서 완전 제외, 참고값으로만 원본 보관(이 스토리에서 추가 작업 없음). (3) washing_flag null의 UI 표시는 2.4/Epic 3 스코프, 이 스토리는 DB에 null 정확 저장까지만 책임.

## scoring.md 산식 (verbatim, 오늘자 강화 반영)

```
달성률   achievement_rate = actual_metric / target_metric        (target > 0)
진척률   progress_rate    = (today - period_start) / (period_end - period_start)   → [0,1] 클램프
갭       gap              = actual_metric - target_metric

washing_flag = (progress_rate >= 0.5)                 -- 목표기간 절반 이상 경과
            AND (achievement_rate < 0.6)              -- 목표의 60% 미달
            AND (buyback_planned AND buyback_retired_amount = 0)  -- 약속했으나 소각 '확정 0'

> null ≠ 소각 안 함: buyback_retired_amount IS NULL은 "모름"이지 "소각 안 함"의 증거가 아니다.
> NOT (NULL > 0)을 False→"미소각"으로 강제하면 미공시 기업이 워싱으로 오판된다. 소각 항은
> 확정 0(공시된 활동 없음)일 때만 워싱 성립, null이면 washing_flag도 null(판정 불가)로 전파.

buyback_status = retired(소각완료) / purchased_only(매입만) / none(미실행) / unknown(취득·소각
중 하나라도 null → 판정 불가). purchased_only는 buyback_amount>0 AND buyback_retired_amount=0
처럼 양쪽 모두 확정일 때만 부여(소각이 null이면 unknown).

execution_score = 100 * clamp(
      0.5 * min(achievement_rate, 1.0)          -- 목표 달성 (가중 0.5)
    + 0.3 * (buyback_executed ? 1 : 0)          -- 자사주 실이행 (가중 0.3)
    + 0.2 * min(actual_payout / target_payout, 1.0)  -- 배당 이행 (가중 0.2)
    , 0, 1)

파라미터(config.py): WASHING_PROGRESS_MIN=0.5, WASHING_ACHIEVEMENT_MAX=0.6,
SCORE_W_ACHIEVEMENT=0.5, SCORE_W_BUYBACK=0.3, SCORE_W_PAYOUT=0.2
```

## 아키텍처 제약

- **AD-1**: valuation_metrics 지표는 VIEW가 계산한 값을 읽기만(파이썬 재계산 금지). achievement_rate 등 스코어는 AD-4가 gap_engine(Python)에 배정한 책임.
- **AD-2**: SQL은 repository에서만. gap_engine.py는 dict/스칼라만 다룸.
- **AD-4**: valueup_score의 유일 writer는 gap_engine.
- **AD-7 확장**: valueup_score 자연키 (corp_code, as_of).
- **AD-8**: valueup_score에 as_of 컬럼, progress_rate의 "today"는 인자로 받은 as_of(시스템 시계 금지).
- **NFR2**: 계산 불가는 결과 null, 예외로 배치 중단 금지.
- **NFR3**: 임계치·가중치는 config.py 주입(이미 존재).

## 전체 코드 (verbatim, 축약 없음)

### `app/models.py` — `ValueupScore` (신규)

```python
class ValueupScore(Base):
    """Value-up 갭 스코어 (writer = gap_engine, AD-4). 자연키 (corp_code, as_of), AD-8.

    achievement_rate·progress_rate·execution_score·washing_flag는 계산 불가(입력 애매/누락)
    시 null(NFR2, "null > 틀린 값"). washing_flag는 특히 null을 False로 강제하지 않는다
    (null=판단불가, scoring.md 2026-07-10 강화). Boolean 컬럼 전부 nullable — null 전파 필수.
    """

    __tablename__ = "valueup_score"
    __table_args__ = (
        UniqueConstraint("corp_code", "as_of", name="uq_valueup_score_corp_asof"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    as_of: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD (progress_rate의 today)
    achievement_rate: Mapped[float | None] = mapped_column(Float)  # actual_roe/target_roe
    progress_rate: Mapped[float | None] = mapped_column(Float)  # 연도 단위, [0,1] 클램프
    execution_score: Mapped[float | None] = mapped_column(Float)  # 0~100
    washing_flag: Mapped[bool | None] = mapped_column(Boolean)
    buyback_executed: Mapped[bool | None] = mapped_column(Boolean)
    buyback_retired: Mapped[bool | None] = mapped_column(Boolean)
    buyback_status: Mapped[str | None] = mapped_column(String(20))  # retired/purchased_only/none/unknown
```

### `alembic/versions/0008_valueup_score.py` (신규, 전체)

```python
"""valueup_score table

Revision ID: 0008_valueup_score
Revises: 0007_ownership
Create Date: 2026-07-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_valueup_score"
down_revision: str | None = "0007_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "valueup_score",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "corp_code",
            sa.String(length=8),
            sa.ForeignKey("company.corp_code"),
            nullable=False,
            index=True,
        ),
        sa.Column("as_of", sa.String(length=10), nullable=False),
        sa.Column("achievement_rate", sa.Float),
        sa.Column("progress_rate", sa.Float),
        sa.Column("execution_score", sa.Float),
        sa.Column("washing_flag", sa.Boolean),
        sa.Column("buyback_executed", sa.Boolean),
        sa.Column("buyback_retired", sa.Boolean),
        sa.Column("buyback_status", sa.String(length=20)),
        sa.UniqueConstraint("corp_code", "as_of", name="uq_valueup_score_corp_asof"),
    )


def downgrade() -> None:
    op.drop_table("valueup_score")
```

### `app/repositories/valueup_score.py` (신규, 전체)

```python
"""valueup_score 입력 조회 + 멱등 upsert 저장소 (AD-2: SQL은 여기서만).

gap_engine(app/analysis/gap_engine.py)의 유일한 DB 접근 지점. 세 가지 읽기(공시 목표·
실적 지표·자사주 원천)와 한 가지 쓰기(스코어 upsert)로 구성. gap_engine 자체는 dict/스칼라만
다루고 SQL을 직접 실행하지 않는다(AD-2).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Financial, ValueupPlan, ValueupScore


def latest_valueup_plan(
    session: Session, corp_code: str, as_of: str
) -> dict[str, Any] | None:
    """as_of 이전(포함) 최신 valueup_plan 1건. 여러 공시 중 as_of 직전 최신 것을 target으로 채택
    (2026-07-10 리드 결정 A: 기간-포함 판정 대신 단순·재현 가능한 규칙).
    """
    stmt = (
        select(ValueupPlan)
        .where(
            ValueupPlan.corp_code == corp_code,
            ValueupPlan.disclosure_date <= as_of,
        )
        .order_by(ValueupPlan.disclosure_date.desc())
        .limit(1)
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        return None
    return {
        "target_roe": obj.target_roe,
        "target_payout_ratio": obj.target_payout_ratio,
        "target_pbr": obj.target_pbr,  # 계산 미사용, 참고 보관만(리드 결정)
        "period_start": obj.period_start,
        "period_end": obj.period_end,
        "buyback_planned": obj.buyback_planned,
    }


def latest_metrics(session: Session, corp_code: str, as_of: str) -> dict[str, Any] | None:
    """as_of 이전(포함) 최신 (year,quarter) valuation_metrics 행. look-ahead 방지를 위해
    as_of 연도 이후 실적은 제외(AD-1: 뷰가 계산한 값을 읽기만).
    """
    as_of_year = int(as_of[:4])
    row = session.execute(
        text(
            "SELECT roe, payout_ratio FROM valuation_metrics "
            "WHERE corp_code = :cc AND year <= :yr "
            "ORDER BY year DESC, quarter DESC LIMIT 1"
        ),
        {"cc": corp_code, "yr": as_of_year},
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def latest_financial_buyback(
    session: Session, corp_code: str, as_of: str
) -> dict[str, Any] | None:
    """as_of 이전(포함) 최신 (year,quarter) financials의 buyback 수량 필드."""
    as_of_year = int(as_of[:4])
    stmt = (
        select(Financial)
        .where(Financial.corp_code == corp_code, Financial.year <= as_of_year)
        .order_by(Financial.year.desc(), Financial.quarter.desc())
        .limit(1)
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        return None
    return {
        "buyback_amount": obj.buyback_amount,
        "buyback_retired_amount": obj.buyback_retired_amount,
    }


def upsert_valueup_score(session: Session, rec: dict[str, Any]) -> ValueupScore:
    """(corp_code, as_of) 자연키 기준 valueup_score upsert(AD-7 확장 패턴).

    gap_engine 산출값은 항상 그 as_of의 '권위 있는 재계산 결과'이므로 null 포함 전체
    교체한다(valueup_plan upsert와 동일 원칙 — 재계산 시 과거 오탐이 null로 정정되게).
    """
    stmt = select(ValueupScore).where(
        ValueupScore.corp_code == rec["corp_code"],
        ValueupScore.as_of == rec["as_of"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = ValueupScore(corp_code=rec["corp_code"], as_of=rec["as_of"])
        session.add(obj)
    for field in (
        "achievement_rate", "progress_rate", "execution_score", "washing_flag",
        "buyback_executed", "buyback_retired", "buyback_status",
    ):
        setattr(obj, field, rec.get(field))
    return obj
```

### `app/analysis/gap_engine.py` (신규, 전체)

```python
"""Value-up 갭 스코어링 엔진 (writer = 이 모듈, AD-4).

Epic 1(수집)과 다른 새 패턴: HTTP 어댑터가 아니라 **순수 계산**. 입력은 이미 DB에 있다
(valuation_metrics 뷰 + valueup_plan + financials.buyback_*). 산식은 scoring.md 참조.

null 전파가 핵심 계약(2026-07-10 코드리뷰로 scoring.md 강화): 입력이 애매/누락이면
0이나 False로 강제하지 않고 해당 스코어도 null로 전파한다(NFR2 "null > 틀린 값").
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Company
from app.repositories import valueup_score as repo


def _safe_ratio(actual: float | None, target: float | None) -> float | None:
    """target이 없거나 0 이하면 계산 불가(0 나눗셈·역설 방어) → None."""
    if actual is None or target is None or target <= 0:
        return None
    return actual / target


def _progress_rate(
    period_start: str | None, period_end: str | None, as_of_year: int
) -> float | None:
    """계획기간(연도 문자열) 대비 진척률, [0,1] 클램프. 연 단위 정밀도만(입력이 연도뿐)."""
    if period_start is None or period_end is None:
        return None
    try:
        start, end = int(period_start), int(period_end)
    except (TypeError, ValueError):
        return None
    if end <= start:
        return None
    raw = (as_of_year - start) / (end - start)
    return max(0.0, min(1.0, raw))


def _achievement_rate(actual_roe: float | None, target_roe: float | None) -> float | None:
    """achievement_rate = 실제 ROE / 목표 ROE. ROE 단독(배당은 execution_score에서 별도 가중,
    이중반영 방지 — 2026-07-10 리드 결정). target_pbr은 산식 미사용."""
    return _safe_ratio(actual_roe, target_roe)


def _buyback_signals(
    amount: int | None, retired_amount: int | None
) -> tuple[bool | None, bool | None, str]:
    """(buyback_executed, buyback_retired, buyback_status). 수량 null=unknown, 0=확정 없음."""
    executed = None if amount is None else amount > 0
    retired = None if retired_amount is None else retired_amount > 0
    if executed is None or retired is None:
        status = "unknown"
    elif retired:
        status = "retired"
    elif executed:
        status = "purchased_only"
    else:
        status = "none"
    return executed, retired, status


def _execution_score(
    achievement_rate: float | None,
    buyback_executed: bool | None,
    actual_payout: float | None,
    target_payout: float | None,
    w_achievement: float,
    w_buyback: float,
    w_payout: float,
) -> float | None:
    """execution_score = 100*clamp(w_a*min(achv,1) + w_b*(executed?1:0) + w_p*min(payout,1)).

    세 항 중 하나라도 계산 불가면 0으로 메우지 않고 전체 null(AC5).
    """
    payout_ratio = _safe_ratio(actual_payout, target_payout)
    if achievement_rate is None or buyback_executed is None or payout_ratio is None:
        return None
    raw = (
        w_achievement * min(achievement_rate, 1.0)
        + w_buyback * (1.0 if buyback_executed else 0.0)
        + w_payout * min(payout_ratio, 1.0)
    )
    return 100 * max(0.0, min(1.0, raw))


def _washing_flag(
    progress_rate: float | None,
    achievement_rate: float | None,
    buyback_planned: bool | None,
    buyback_retired: bool | None,
    progress_min: float,
    achievement_max: float,
) -> bool | None:
    """입력 중 하나라도 None이면 결과도 None(판단 불가). False로 강제 금지(scoring.md 계약)."""
    if (
        progress_rate is None
        or achievement_rate is None
        or buyback_planned is None
        or buyback_retired is None
    ):
        return None
    return (
        progress_rate >= progress_min
        and achievement_rate < achievement_max
        and buyback_planned
        and not buyback_retired
    )


def run(
    session: Session, as_of: str, corp_codes: Sequence[str] | None = None
) -> int:
    """as_of 기준으로 corp별 valueup_score를 계산·upsert. 적재 행 수 반환.

    valueup_plan이 없는 종목은 목표가 없어 갭을 정의할 수 없으므로 행을 만들지 않는다
    (1-6 no-data 교훈과 동일 원칙).
    """
    if corp_codes is None:
        corp_codes = session.scalars(select(Company.corp_code)).all()
    as_of_year = int(as_of[:4])

    count = 0
    for corp_code in corp_codes:
        plan = repo.latest_valueup_plan(session, corp_code, as_of)
        if plan is None:
            continue

        metrics = repo.latest_metrics(session, corp_code, as_of)
        buyback = repo.latest_financial_buyback(session, corp_code, as_of)
        actual_roe = metrics.get("roe") if metrics else None
        actual_payout = metrics.get("payout_ratio") if metrics else None
        amount = buyback.get("buyback_amount") if buyback else None
        retired_amount = buyback.get("buyback_retired_amount") if buyback else None

        achievement_rate = _achievement_rate(actual_roe, plan["target_roe"])
        progress_rate = _progress_rate(plan["period_start"], plan["period_end"], as_of_year)
        executed, retired, status = _buyback_signals(amount, retired_amount)
        execution_score = _execution_score(
            achievement_rate, executed, actual_payout, plan["target_payout_ratio"],
            settings.score_w_achievement, settings.score_w_buyback, settings.score_w_payout,
        )
        washing_flag = _washing_flag(
            progress_rate, achievement_rate, plan["buyback_planned"], retired,
            settings.washing_progress_min, settings.washing_achievement_max,
        )

        repo.upsert_valueup_score(
            session,
            {
                "corp_code": corp_code,
                "as_of": as_of,
                "achievement_rate": achievement_rate,
                "progress_rate": progress_rate,
                "execution_score": execution_score,
                "washing_flag": washing_flag,
                "buyback_executed": executed,
                "buyback_retired": retired,
                "buyback_status": status,
            },
        )
        count += 1

    session.flush()
    return count
```

### `tests/test_gap_engine.py` (신규, 전체)

```python
"""Story 2.1 — Value-up 갭 스코어링 엔진 검증 (순수 함수 + 통합, DB는 SQLite in-memory)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.analysis.gap_engine import (
    _achievement_rate,
    _buyback_signals,
    _execution_score,
    _progress_rate,
    _safe_ratio,
    _washing_flag,
    run,
)
from app.models import Base, Company, Financial, ValueupPlan, ValueupScore
from app.sql_views import CREATE_VALUATION_METRICS


# ── T3: 순수 함수 단위 테스트 (DB 미접촉) ──

def test_safe_ratio_normal() -> None:
    assert _safe_ratio(8.0, 10.0) == 0.8


def test_safe_ratio_target_zero_or_negative_is_none() -> None:
    assert _safe_ratio(8.0, 0.0) is None
    assert _safe_ratio(8.0, -5.0) is None


def test_safe_ratio_missing_input_is_none() -> None:
    assert _safe_ratio(None, 10.0) is None
    assert _safe_ratio(8.0, None) is None


def test_progress_rate_mid_period() -> None:
    """3년 계획(2024~2027) 중 1년 경과 → 1/3."""
    assert _progress_rate("2024", "2027", 2025) == pytest.approx(1 / 3)


def test_progress_rate_before_start_clamps_zero() -> None:
    assert _progress_rate("2024", "2027", 2023) == 0.0


def test_progress_rate_after_end_clamps_one() -> None:
    assert _progress_rate("2024", "2027", 2030) == 1.0


def test_progress_rate_invalid_period_is_none() -> None:
    assert _progress_rate(None, "2027", 2025) is None
    assert _progress_rate("2024", None, 2025) is None
    assert _progress_rate("2027", "2024", 2025) is None  # end<=start
    assert _progress_rate("2024", "2024", 2025) is None  # end==start, 0나눗셈 방어
    assert _progress_rate("abc", "2027", 2025) is None  # 파싱 실패


def test_achievement_rate_normal() -> None:
    assert _achievement_rate(8.0, 10.0) == pytest.approx(0.8)


def test_achievement_rate_target_missing_or_nonpositive_is_none() -> None:
    assert _achievement_rate(8.0, None) is None
    assert _achievement_rate(8.0, 0.0) is None
    assert _achievement_rate(None, 10.0) is None


def test_buyback_signals_retired() -> None:
    executed, retired, status = _buyback_signals(3_000_000, 1_000_000)
    assert executed is True
    assert retired is True
    assert status == "retired"


def test_buyback_signals_purchased_only() -> None:
    executed, retired, status = _buyback_signals(3_000_000, 0)
    assert executed is True
    assert retired is False
    assert status == "purchased_only"


def test_buyback_signals_none_activity() -> None:
    executed, retired, status = _buyback_signals(0, 0)
    assert executed is False
    assert retired is False
    assert status == "none"


def test_buyback_signals_unknown_when_either_missing() -> None:
    assert _buyback_signals(None, 0)[2] == "unknown"
    assert _buyback_signals(3_000_000, None)[2] == "unknown"
    assert _buyback_signals(None, None) == (None, None, "unknown")


def test_execution_score_normal() -> None:
    # achievement=0.8(0.5) + buyback=1(0.3) + payout=1.0달성(0.2) → 100*(0.4+0.3+0.2)=90
    score = _execution_score(
        achievement_rate=0.8, buyback_executed=True,
        actual_payout=35.0, target_payout=30.0,  # 초과달성 → min(,1.0)=1.0
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
    )
    assert score == pytest.approx(90.0)


def test_execution_score_caps_overachievement() -> None:
    """achievement_rate 150%여도 min(,1.0)으로 캡."""
    score = _execution_score(
        achievement_rate=1.5, buyback_executed=True,
        actual_payout=30.0, target_payout=30.0,
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
    )
    assert score == pytest.approx(100.0)


def test_execution_score_none_when_achievement_missing() -> None:
    assert _execution_score(
        achievement_rate=None, buyback_executed=True,
        actual_payout=30.0, target_payout=30.0,
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
    ) is None


def test_execution_score_none_when_buyback_unknown() -> None:
    assert _execution_score(
        achievement_rate=0.8, buyback_executed=None,
        actual_payout=30.0, target_payout=30.0,
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
    ) is None


def test_execution_score_none_when_payout_ratio_undefined() -> None:
    assert _execution_score(
        achievement_rate=0.8, buyback_executed=True,
        actual_payout=30.0, target_payout=None,
        w_achievement=0.5, w_buyback=0.3, w_payout=0.2,
    ) is None


def test_washing_flag_true_case() -> None:
    assert _washing_flag(
        progress_rate=0.6, achievement_rate=0.4, buyback_planned=True,
        buyback_retired=False, progress_min=0.5, achievement_max=0.6,
    ) is True


def test_washing_flag_false_case_achievement_high() -> None:
    assert _washing_flag(
        progress_rate=0.6, achievement_rate=0.9, buyback_planned=True,
        buyback_retired=False, progress_min=0.5, achievement_max=0.6,
    ) is False


def test_washing_flag_false_when_retired_true() -> None:
    assert _washing_flag(
        progress_rate=0.6, achievement_rate=0.4, buyback_planned=True,
        buyback_retired=True, progress_min=0.5, achievement_max=0.6,
    ) is False


def test_washing_flag_null_propagation() -> None:
    """리뷰 핵심 계약: 입력 중 하나라도 None이면 결과도 None(False 강제 금지)."""
    base = dict(
        progress_rate=0.6, achievement_rate=0.4, buyback_planned=True,
        buyback_retired=False, progress_min=0.5, achievement_max=0.6,
    )
    for key in ("progress_rate", "achievement_rate", "buyback_planned", "buyback_retired"):
        kwargs = {**base, key: None}
        assert _washing_flag(**kwargs) is None, f"{key}=None should propagate to None"


# ── T4: 통합 테스트 (SQLite in-memory + valuation_metrics 뷰) ──

@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))
    return eng


def _seed(session: Session, corp_code: str = "00000001") -> None:
    session.add(Company(corp_code=corp_code, corp_name="테스트", market="KOSPI"))
    session.add(Financial(
        corp_code=corp_code, year=2025, quarter=4,
        revenue=1000, net_income=80, operating_income=100, depreciation=10,
        equity=1000, total_assets=2000, total_liabilities=1000, cash=100,
        total_debt=200, dividend_total=24,
        buyback_amount=3_000_000, buyback_retired_amount=0,
    ))
    session.add(ValueupPlan(
        corp_code=corp_code, disclosure_date="2024-03-01",
        target_roe=10.0, target_payout_ratio=30.0, target_pbr=1.2,
        period_start="2024", period_end="2027", buyback_planned=True,
    ))
    session.commit()


def test_run_computes_and_upserts_score(engine) -> None:
    """AC1/2/4/5/6: end-to-end 계산이 정확히 나온다."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        n = run(s, as_of="2025-12-31")
        s.commit()
        assert n == 1
        row = s.scalars(select(ValueupScore)).one()
        # actual_roe = net_income/equity*100 = 80/1000*100 = 8.0 → achievement = 8/10 = 0.8
        assert row.achievement_rate == pytest.approx(0.8)
        # progress: (2025-2024)/(2027-2024) = 1/3
        assert row.progress_rate == pytest.approx(1 / 3)
        assert row.buyback_executed is True
        assert row.buyback_retired is False  # 확정 0
        assert row.buyback_status == "purchased_only"
        # washing: progress(1/3)<0.5 → False(달성률 낮아도 진척 미달로 워싱 아님)
        assert row.washing_flag is False
        assert row.execution_score is not None


def test_run_skips_corp_without_plan(engine) -> None:
    """AC1: valueup_plan 없는 종목은 행 자체를 만들지 않는다(no-data 취급)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000002", corp_name="계획없음"))
        s.commit()
        n = run(s, as_of="2025-12-31", corp_codes=["00000002"])
        s.commit()
        assert n == 0
        assert s.scalar(select(ValueupScore)) is None


def test_run_is_idempotent(engine) -> None:
    """AC7: 같은 (corp_code, as_of) 재실행 시 중복 없이 갱신."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        run(s, as_of="2025-12-31")
        s.commit()
        run(s, as_of="2025-12-31")  # 재실행
        s.commit()
        rows = s.scalars(select(ValueupScore)).all()
        assert len(rows) == 1


def test_run_picks_latest_disclosure_before_as_of(engine) -> None:
    """리드 결정 A: as_of 이전 최신 공시 채택(2024-03 목표10% 대신 2025-06 목표12%)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)  # target_roe=10.0 @ 2024-03-01
        s.add(ValueupPlan(
            corp_code="00000001", disclosure_date="2025-06-01",
            target_roe=12.0, period_start="2025", period_end="2028",
            buyback_planned=True,
        ))
        s.commit()
        run(s, as_of="2025-12-31")
        s.commit()
        row = s.scalars(select(ValueupScore)).one()
        # actual_roe=8.0 → 8/12 (최신 공시 target) 아니라 8/10이면 구버전 채택 오류
        assert row.achievement_rate == pytest.approx(8.0 / 12.0)


def test_run_null_metrics_propagate_to_null_score(engine) -> None:
    """financials/metrics 없는 종목: plan은 있으나 실적 없음 → achievement_rate null."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000003", corp_name="실적없음"))
        s.add(ValueupPlan(
            corp_code="00000003", disclosure_date="2024-01-01",
            target_roe=10.0, period_start="2024", period_end="2027",
            buyback_planned=True,
        ))
        s.commit()
        run(s, as_of="2025-12-31", corp_codes=["00000003"])
        s.commit()
        row = s.scalars(select(ValueupScore)).one()
        assert row.achievement_rate is None
        assert row.execution_score is None
        assert row.buyback_status == "unknown"
        assert row.washing_flag is None
```

### 참고: `app/repositories/financials.py:upsert_financial` (비교용 — None-safe 부분갱신 정책, 대비되는 기존 패턴)

```python
def upsert_financial(session: Session, rec: dict) -> Financial:
    """(corp_code, year, quarter) 자연키 기준 financials upsert."""
    stmt = select(Financial).where(
        Financial.corp_code == rec["corp_code"],
        Financial.year == rec["year"],
        Financial.quarter == rec["quarter"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = Financial(
            corp_code=rec["corp_code"], year=rec["year"], quarter=rec["quarter"]
        )
        session.add(obj)
    if "fs_div" in rec:
        obj.fs_div = rec["fs_div"]
    # 값 필드는 None이 아닌 경우에만 갱신 — 매핑 실패로 기존 non-null이 지워지지 않게
    for field in (
        "revenue", "net_income", "operating_income", "depreciation",
        "equity", "total_assets", "total_liabilities", "cash", "total_debt",
        "dividend_total", "buyback_amount", "buyback_retired_amount",
    ):
        if rec.get(field) is not None:
            setattr(obj, field, rec[field])
    return obj
```

## 이미 알려진 것 / 의도된 결정 (중복 지적 불필요)

- **upsert 정책이 financials와 반대(의도적)**: `upsert_valueup_score`는 None 포함 전체 교체, `upsert_financial`은 None-safe 부분갱신. 이유: financials는 여러 소스가 부분 필드씩 채우는 수집 원천이라 None=아직 안 채워짐. valueup_score는 매번 gap_engine이 **전체 재계산**한 권위 있는 결과라 이전 계산이 오답이었다면 null로 정정돼야 함(예: 잘못된 실적으로 achievement_rate가 non-null이었다가 재계산 시 target 삭제로 null이 되면 그 null이 맞는 값).
- **plan 없는 corp는 행 미생성**: 1-6 no-data 패턴 재사용, 의도됨.
- **연도 단위 progress_rate**: 입력(period_start/end)이 4자리 연도 문자열이라 구조적 한계, 문서화됨.
- **target_pbr 미사용**: 리드가 명시적으로 확정(계산 제외, 원본 valueup_plan에 참고값으로만 존재, 이 스토리는 추가 저장 안 함).
- **washing_flag null → DB엔 null 그대로**: UI 표시("판단 불가")는 2.4/Epic 3 스코프로 명시적 이관.
- **검증**: pytest 127 passed(gap_engine 27 신규, 기존 100 회귀 0).

## 출력 형식
`[High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정`. 없으면 "clean".
특히 답해줘: (1) `_washing_flag`의 "하나라도 None→전체 None" 규칙이 3치 논리상 과도하게 보수적인 지점이 있는지(예: buyback_retired=True 확정인데 progress_rate가 null인 경우도 washing은 사실 확정 False여야 하는 게 아닌지), (2) `latest_metrics`/`latest_financial_buyback`의 연도만 필터하는 look-ahead 방지가 분기 단위로도 안전한지, (3) `latest_valueup_plan`의 문자열 날짜 비교(`disclosure_date <= as_of`)가 실제로 안전한 날짜 비교인지 아니면 포맷 가정이 깨지는 입력이 있는지.
