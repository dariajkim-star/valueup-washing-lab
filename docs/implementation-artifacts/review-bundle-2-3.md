# 코드 리뷰 요청 — 밸류업 워싱 스크리너 Story 2.3 (M&A Target Score 엔진, mna_engine)

너는 엄격한(adversarial) 시니어 코드 리뷰어야. 아래 스토리/AC, 산식, **전체 코드(verbatim, 축약 없음)**를 보고
버그·규약 위반·엣지케이스·백분위 수학의 정확성 문제를 찾아줘.
출력: `[High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정`. 칭찬 생략, 없으면 "clean".

**이번 핵심 = cross-sectional 백분위 수학의 정확성 + 모집단 구성의 시간 정렬 + 엄격 null 전파**라 특히:
- `_percentile_rank`의 정의: "엄격히 작은 값 수 / (N-1)", population은 **자기 자신 포함** 전체 모집단 — 동점·퇴화 분포(전원 동일값이면 전원 rank 0 → pct_low 전원 1.0)·자기포함 편향이 스코어 의미를 왜곡하는 경우가 있는지
- `corp_codes` 부분집합 실행 시에도 population은 전체 시장 기준(의도) — 이 설계에 구멍이 있는지(예: 부분 실행과 전체 실행의 결과 불일치 시나리오)
- `latest_macro_percentile_basis`: "as_of 이전 최신 관측값"을 현재값으로 쓰는데, 마지막 관측이 아주 오래됐어도(예: 2년 전) 그대로 채택 — 신선도(staleness) 가드 부재가 문제인지
- look-ahead: metrics는 같은 해 사업보고서(quarter=4) 배제(2.1과 동일 규칙), ownership은 `as_of <=` 문자열 비교, macro는 `date <= as_of` — 각각 시간 정렬이 안전한지
- 3요소 전부 None이면 행 미생성+기존 행 삭제(reconciliation) — 이 정리 로직이 데이터를 잘못 지우는 시나리오가 있는지
- 엄격 null: 서브지표 하나 None → 요소 None → 총점 None — AC6과 구현이 일치하는지

## 스토리 & AC (verbatim)

- As a 애널리스트, 인수 매력도가 4요소 점수로 산출되는 것 — M&A 타겟 후보 발굴.
- **AC1**: `mna_engine.run(session, as_of, corp_codes=None)` 실행 시 `mna_score`(corp_code, as_of, mna_target_score, valuation_score, capacity_score, ownership_score, macro_score) 적재(AD-10: mna_engine이 유일 writer).
- **AC2**: `valuation_score = avg(pct_rank_low(ev_ebitda), pct_rank_low(pbr))`, `capacity_score = avg(pct_rank_low(debt_ratio), pct_rank_high(net_cash), pct_rank_high(ebitda_margin))` — **전체 종목 모집단 내 백분위**(look-ahead 방지: 같은 해 사업보고서 배제).
- **AC3**: `ownership_score = avg(pct_rank_low(largest_shareholder_pct), pct_rank_high(treasury_stock_pct))`.
- **AC4**: `macro_score = pct_rank_low(as_of 시점 기준금리, 역사적 base_rate 분포)` — 전 종목 공통, as_of당 1회.
- **AC5**: `mna_target_score = 100 * (0.35*valuation + 0.25*capacity + 0.25*ownership + 0.15*macro)`, 가중치 config 주입.
- **AC6**: 서브지표 null이거나 peer<2면 백분위 제외 → **요소의 서브지표가 하나라도 null이면 요소 점수 null**, 요소 하나라도 null이면 mna_target_score null(엄격, 리드 결정).
- **AC7**: 멱등 upsert + 근거 잃은 기존 행 reconciliation.
- **AC8**: 백분위 양방향·null 전파·look-ahead·멱등 fixture 테스트, 기존 136 회귀 0.

**리드 확정 결정 3건**: (1) 요소 null=엄격(있는 것만 평균 금지 — 결측 잦은 지표의 암묵적 가중치 왜곡 방지). (2) 매크로 백분위 모집단=as_of 이전 전체 역사(롤링 윈도우 아님). (3) v1 전체시장 단일 모집단 + **grouping seam**(`_build_populations`의 `group_of` 콜러블)만 확보 — sector peer-group은 후속 2-7(택소노미+small-N 폴백), 업종별 변수 세트는 그 뒤.

## scoring.md M&A 산식 (verbatim)

```
mna_target_score = 100 * (
      0.35 * valuation_score    -- 저평가: EV/EBITDA·PBR 낮을수록 ↑ (역백분위)
    + 0.25 * capacity_score     -- 인수여력: 부채비율 낮음·순현금 많음·EBITDA마진 ↑
    + 0.25 * ownership_score    -- 지배구조: 최대주주 지분율 낮음·자사주 비중 ↑ (뺏기 쉬움)
    + 0.15 * macro_score        -- 매크로: 기준금리 낮을수록 ↑ (차입인수 유리)
)
- valuation_score = avg(pct_rank_low(ev_ebitda), pct_rank_low(pbr))
- capacity_score = avg(pct_rank_low(debt_ratio), pct_rank_high(net_cash), pct_rank_high(ebitda_margin))
- ownership_score = avg(pct_rank_low(largest_shareholder_pct), pct_rank_high(treasury_stock_pct))
- macro_score = pct_rank_low(기준금리) — 종목 무관, as_of 시점 값
- 가중치 config: MNA_W_VALUATION=0.35, MNA_W_CAPACITY=0.25, MNA_W_OWNERSHIP=0.25, MNA_W_MACRO=0.15 (합 1.0 검증됨)
- pct_rank_low=낮을수록 높은 점수, pct_rank_high=높을수록 높은 점수
```

## 아키텍처 제약

- **AD-1**: valuation_metrics 지표는 VIEW 계산값 읽기만. **AD-2**: SQL은 repository에서만(2.1 리뷰에서 엔진의 직접 SQL이 지적된 전례 — 이번엔 전부 repositories/mna_score.py 경유). **AD-10**: mna_score 유일 writer=mna_engine. **NFR2**: 계산 불가=null. **NFR3**: 가중치 config 주입.
- 입력 테이블: `valuation_metrics` VIEW(ev_ebitda·pbr·debt_ratio·net_cash·ebitda_margin, LEFT JOIN prices라 가격 없으면 pbr/ev_ebitda null), `ownership`(largest_shareholder_pct·treasury_stock_pct, as_of 문자열 YYYY-MM-DD), `macro_indicator`(indicator·date·value).

## 전체 코드 (verbatim, 축약 없음)

### `app/models.py` — `MnaScore` (신규)

```python
class MnaScore(Base):
    """M&A Target Score (writer = mna_engine, AD-10). 자연키 (corp_code, as_of).

    cross-sectional 백분위(시장 내 상대 순위) 기반 — 요소 서브지표가 하나라도 null이면
    요소 점수 null, 요소가 하나라도 null이면 mna_target_score null(엄격, 리드 결정 2026-07-10).
    macro_score는 종목 무관 공통값(as_of당 1회 계산).
    """

    __tablename__ = "mna_score"
    __table_args__ = (
        UniqueConstraint("corp_code", "as_of", name="uq_mna_score_corp_asof"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    as_of: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD
    mna_target_score: Mapped[float | None] = mapped_column(Float)  # 0~100
    valuation_score: Mapped[float | None] = mapped_column(Float)  # 0~1 (저평가)
    capacity_score: Mapped[float | None] = mapped_column(Float)  # 0~1 (인수여력)
    ownership_score: Mapped[float | None] = mapped_column(Float)  # 0~1 (지배구조 취약성)
    macro_score: Mapped[float | None] = mapped_column(Float)  # 0~1, 종목 무관 공통
```

### `app/repositories/mna_score.py` (신규, 전체)

```python
"""mna_score 배치 입력 조회 + 멱등 upsert 저장소 (AD-2: SQL은 여기서만).

mna_engine(app/analysis/mna_engine.py)의 유일한 DB 접근 지점. 2.1(gap_engine, 종목별 단건
조회)과 달리 **cross-sectional 백분위**라 전체 모집단을 배치로 한 번에 가져온다 — 종목 루프
안에서 단건 쿼리하면 N+1이자 설계 오류(한 종목의 점수가 전체 분포에 의존).

look-ahead 부분차단은 2.1(valueup_score.py)과 동일 규칙: 같은 연도의 사업보고서(quarter=4)는
그 해 안에 공시될 수 없으므로(통상 다음해 3월) 배제 — `year<yr OR (year=yr AND quarter<4)`.
1~3분기 동일연도 시차는 공통 defer(deferred-work.md 2-1 섹션).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Company, MacroIndicator, MnaScore, Ownership


def list_all_corp_codes(session: Session) -> list[str]:
    """전 종목 corp_code 목록(run()의 corp_codes 기본값)."""
    return list(session.scalars(select(Company.corp_code)).all())


def all_latest_metrics(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """전 종목의 as_of 시점 최신 (year,quarter) valuation_metrics 행(배치).

    corp_code → {ev_ebitda, pbr, debt_ratio, net_cash, ebitda_margin}.
    look-ahead 배제 후 corp별 최신 1행을 Python에서 선택(정렬된 결과 첫 등장 유지 —
    SQLite/PostgreSQL 양쪽에서 동일 동작, 데이터 규모상 충분).
    """
    as_of_year = int(as_of[:4])
    rows = session.execute(
        text(
            "SELECT corp_code, ev_ebitda, pbr, debt_ratio, net_cash, ebitda_margin "
            "FROM valuation_metrics "
            "WHERE year < :yr OR (year = :yr AND quarter < 4) "
            "ORDER BY corp_code, year DESC, quarter DESC"
        ),
        {"yr": as_of_year},
    ).mappings().all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row["corp_code"]
        if code not in latest:  # 정렬상 corp별 첫 행 = 최신
            latest[code] = {
                "ev_ebitda": row["ev_ebitda"],
                "pbr": row["pbr"],
                "debt_ratio": row["debt_ratio"],
                "net_cash": row["net_cash"],
                "ebitda_margin": row["ebitda_margin"],
            }
    return latest


def all_latest_ownership(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """전 종목의 as_of 이전(포함) 최신 ownership 행(배치).

    corp_code → {largest_shareholder_pct, treasury_stock_pct}.
    as_of 근사치(비12월 결산 라벨오류)는 1-6 known-limitation 그대로.
    """
    stmt = (
        select(Ownership)
        .where(Ownership.as_of <= as_of)
        .order_by(Ownership.corp_code, Ownership.as_of.desc())
    )
    latest: dict[str, dict[str, Any]] = {}
    for obj in session.scalars(stmt):
        if obj.corp_code not in latest:
            latest[obj.corp_code] = {
                "largest_shareholder_pct": obj.largest_shareholder_pct,
                "treasury_stock_pct": obj.treasury_stock_pct,
            }
    return latest


def latest_macro_percentile_basis(
    session: Session, as_of: str, indicator: str = "base_rate"
) -> tuple[float | None, list[float]]:
    """(as_of 이전 최신 지표값, as_of 이전 전체 역사 시계열) — 매크로 백분위 기준.

    모집단 = as_of 이전 전체 관측값(리드 결정: 롤링 윈도우 아님, ECOS 수집 기간 길어지면
    후속 재검토). as_of 이후 관측은 look-ahead라 제외.
    """
    stmt = (
        select(MacroIndicator)
        .where(MacroIndicator.indicator == indicator, MacroIndicator.date <= as_of)
        .order_by(MacroIndicator.date.desc())
    )
    objs = list(session.scalars(stmt))
    history = [o.value for o in objs if o.value is not None]
    current = history[0] if history else None  # 최신(내림차순 첫 유효값)
    return current, history


def upsert_mna_score(session: Session, rec: dict[str, Any]) -> MnaScore:
    """(corp_code, as_of) 자연키 기준 mna_score upsert.

    2.1 upsert_valueup_score와 동일 정책: 권위 있는 전체 재계산 결과이므로 null 포함 전체
    교체 + `rec[field]` 직접 인덱싱(키 누락은 프로그래밍 오류 → KeyError로 즉시 노출).
    """
    stmt = select(MnaScore).where(
        MnaScore.corp_code == rec["corp_code"], MnaScore.as_of == rec["as_of"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = MnaScore(corp_code=rec["corp_code"], as_of=rec["as_of"])
        session.add(obj)
    for field in (
        "mna_target_score", "valuation_score", "capacity_score",
        "ownership_score", "macro_score",
    ):
        setattr(obj, field, rec[field])
    return obj


def delete_mna_score(session: Session, corp_code: str, as_of: str) -> None:
    """근거(입력 데이터)를 잃은 (corp_code, as_of)의 오래된 score 정리(2.1 reconciliation
    패턴). 없으면 no-op(멱등)."""
    stmt = select(MnaScore).where(
        MnaScore.corp_code == corp_code, MnaScore.as_of == as_of,
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is not None:
        session.delete(obj)
```

### `app/analysis/mna_engine.py` (신규, 전체)

```python
"""M&A Target Score 엔진 (writer = 이 모듈, AD-10).

2.1(gap_engine, 종목별 독립 계산)과 다른 아키텍처: **cross-sectional 백분위** — 한 종목의
점수가 전체 모집단 분포에 의존한다. 따라서 (1) 전체 모집단을 배치로 먼저 구성하고,
(2) 그 안에서 각 종목의 백분위를 계산하는 2단계 구조. 산식은 scoring.md M&A 섹션 참조.

null 규칙(엄격, 리드 결정 2026-07-10): 요소의 서브지표가 하나라도 null이면 요소 점수 null,
요소가 하나라도 null이면 mna_target_score null — "일부만 알면서 평균 내서 숫자 만들기" 금지
(2.1 execution_score와 동일 원칙, NFR2 "null > 틀린 값").

grouping seam(리드 결정, finance 스코프 분리): 백분위 모집단은 `_build_populations`의
`group_of` 콜러블이 결정한다. v1 = 전체시장 단일 그룹. 후속 2-7이 `company.sector` 기반
peer-group으로 갈아끼울 이음새 — 백분위 계산부는 population 출처를 모른다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.analysis.gap_engine import _AS_OF_RE  # as_of 검증 재사용(중복 정의 금지)
from app.config import settings
from app.repositories import mna_score as repo

# v1 grouping: 전체시장 한 그룹(2-7에서 sector grouping으로 교체될 seam)
_WHOLE_MARKET = "_all"

# (지표명, 방향) — 요소별 서브지표 정의. low=낮을수록 좋음, high=높을수록 좋음.
_VALUATION_INDICATORS = (("ev_ebitda", "low"), ("pbr", "low"))
_CAPACITY_INDICATORS = (("debt_ratio", "low"), ("net_cash", "high"), ("ebitda_margin", "high"))
_OWNERSHIP_INDICATORS = (("largest_shareholder_pct", "low"), ("treasury_stock_pct", "high"))


def _percentile_rank(value: float | None, population: Sequence[float | None]) -> float | None:
    """population 내 value의 백분위(0~1). '엄격히 작은 값 비율' 기준 — 최솟값 0, 최댓값 1,
    동점은 같은 순위. 유효 peer가 2 미만이면 순위가 무의미 → None."""
    if value is None:
        return None
    pop = [v for v in population if v is not None]
    if len(pop) < 2:
        return None
    below = sum(1 for v in pop if v < value)
    return below / (len(pop) - 1)


def _pct_rank_low(value: float | None, population: Sequence[float | None]) -> float | None:
    """낮을수록 좋은 지표(EV/EBITDA·PBR·부채비율·최대주주지분율·기준금리) → 역백분위."""
    rank = _percentile_rank(value, population)
    return None if rank is None else 1.0 - rank


def _pct_rank_high(value: float | None, population: Sequence[float | None]) -> float | None:
    """높을수록 좋은 지표(순현금·EBITDA마진·자사주비중) → 백분위 그대로."""
    return _percentile_rank(value, population)


def _avg_scores(*scores: float | None) -> float | None:
    """서브지표 점수 평균. 하나라도 None이면 전체 None(엄격, 리드 결정 — 결측이 잦은
    지표가 은근히 가중치를 왜곡하는 '있는 것만 평균' 부작용 방지)."""
    if any(s is None for s in scores):
        return None
    return sum(scores) / len(scores)


def _mna_target_score(
    valuation: float | None,
    capacity: float | None,
    ownership: float | None,
    macro: float | None,
    w_valuation: float,
    w_capacity: float,
    w_ownership: float,
    w_macro: float,
) -> float | None:
    """가중합 0~100. 요소 하나라도 None이면 전체 None(NFR2)."""
    if valuation is None or capacity is None or ownership is None or macro is None:
        return None
    return 100 * (
        w_valuation * valuation
        + w_capacity * capacity
        + w_ownership * ownership
        + w_macro * macro
    )


def _build_populations(
    rows: Mapping[str, Mapping[str, Any]],
    group_of: Callable[[str], str],
) -> dict[str, dict[str, list[float]]]:
    """corp별 지표 dict → 그룹별·지표별 population(유효값 리스트).

    grouping seam: `group_of(corp_code) -> 그룹키`. v1은 상수(전체시장), 2-7에서
    sector 버킷으로 교체. 백분위 계산부는 이 함수가 준 population만 소비한다.
    """
    pops: dict[str, dict[str, list[float]]] = {}
    for corp_code, indicators in rows.items():
        group = group_of(corp_code)
        bucket = pops.setdefault(group, {})
        for name, value in indicators.items():
            if value is not None:
                bucket.setdefault(name, []).append(value)
    return pops


def _factor_score(
    indicators: tuple[tuple[str, str], ...],
    corp_row: Mapping[str, Any] | None,
    population: Mapping[str, list[float]],
) -> float | None:
    """요소 점수 = 서브지표 백분위들의 평균(엄격 null). corp 데이터 자체가 없으면 None."""
    if corp_row is None:
        return None
    scores: list[float | None] = []
    for name, direction in indicators:
        value = corp_row.get(name)
        pop = population.get(name, [])
        rank = _pct_rank_low(value, pop) if direction == "low" else _pct_rank_high(value, pop)
        scores.append(rank)
    return _avg_scores(*scores)


def run(
    session: Session, as_of: str, corp_codes: Sequence[str] | None = None
) -> int:
    """as_of 기준 corp별 mna_score를 계산·upsert. 적재 행 수 반환.

    - 백분위 모집단은 corp_codes 부분집합과 무관하게 **전체 시장**(all_latest_* 배치 결과)
      기준 — 부분 실행이어도 순위 기준이 흔들리면 안 된다.
    - 종목별 3요소(valuation/capacity/ownership)가 전부 None이면 행을 만들지 않는다
      (macro는 전 종목 공통이라 그것만으론 종목별 정보가 없음 — all-null 행 방지, 1-6 교훈).
      기존 행이 있으면 정리(2.1 reconciliation 패턴).
    """
    if not _AS_OF_RE.match(as_of):
        raise ValueError(f"as_of는 YYYY-MM-DD 형식이어야 합니다: {as_of!r}")
    if corp_codes is None:
        corp_codes = repo.list_all_corp_codes(session)

    # 1단계: 전체 모집단 배치 구성(cross-sectional — corp 루프 전에 끝나야 함)
    metrics = repo.all_latest_metrics(session, as_of)
    ownership = repo.all_latest_ownership(session, as_of)
    current_rate, rate_history = repo.latest_macro_percentile_basis(session, as_of)

    metric_pops = _build_populations(metrics, group_of=lambda c: _WHOLE_MARKET)
    owner_pops = _build_populations(ownership, group_of=lambda c: _WHOLE_MARKET)
    # macro_score: 종목 무관, as_of당 1회(낮은 금리 = 차입인수 유리 → 역백분위)
    macro_score = _pct_rank_low(current_rate, rate_history)

    count = 0
    for corp_code in corp_codes:
        valuation = _factor_score(
            _VALUATION_INDICATORS, metrics.get(corp_code),
            metric_pops.get(_WHOLE_MARKET, {}),
        )
        capacity = _factor_score(
            _CAPACITY_INDICATORS, metrics.get(corp_code),
            metric_pops.get(_WHOLE_MARKET, {}),
        )
        owner = _factor_score(
            _OWNERSHIP_INDICATORS, ownership.get(corp_code),
            owner_pops.get(_WHOLE_MARKET, {}),
        )
        if valuation is None and capacity is None and owner is None:
            repo.delete_mna_score(session, corp_code, as_of)  # 근거 없는 기존 행 정리
            continue

        total = _mna_target_score(
            valuation, capacity, owner, macro_score,
            settings.mna_w_valuation, settings.mna_w_capacity,
            settings.mna_w_ownership, settings.mna_w_macro,
        )
        repo.upsert_mna_score(
            session,
            {
                "corp_code": corp_code,
                "as_of": as_of,
                "mna_target_score": total,
                "valuation_score": valuation,
                "capacity_score": capacity,
                "ownership_score": owner,
                "macro_score": macro_score,
            },
        )
        count += 1

    session.flush()
    return count
```

### 참고: `app/analysis/gap_engine.py`의 `_AS_OF_RE` (import 재사용)

```python
_AS_OF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
```

### `tests/test_mna_engine.py` — 주요 테스트 요지 (fixture는 FY2024 Q4 실적 + 2025-06-30 가격 + 2024-12-31 ownership + base_rate 시계열, as_of=2025-12-31)

- `_percentile_rank`: [10,20,30,40]에서 10→0.0, 40→1.0, 20→1/3. 동점 [10,10,30]에서 10→0.0. peer<2·value None·population None 포함 처리.
- `_pct_rank_low/high` 방향. `_avg_scores`/`_mna_target_score` 엄격 null. `_build_populations` v1 단일그룹 + sector 콜러블 주입 시 그룹 분리(seam 검증).
- 통합: 시총 1000/3000/9000 3종목 → 최저시총 valuation_score 1.0·최고시총 0.0, ownership 방향, macro 공통값, 총점 순위. ownership 미공시 종목은 ownership_score null → 총점 null(요소별 점수는 채워짐). 같은 해(2025) 사업보고서만 있는 종목은 지표 안 보임(look-ahead). 재실행 멱등. as_of 포맷 거부. **macro look-ahead**: as_of=2024-12-31이면 2025-01 관측(2.5)이 모집단에서 제외돼 3.0이 최저로 rank 1.0.

## 이미 알려진 것 / 의도된 결정 (중복 지적 불필요)

- **엄격 null(리드 확정)**: "있는 서브지표만 평균" 대안은 기각됨(결측 잦은 지표의 암묵적 가중치 왜곡). 실데이터 결측률 확인 후 재검토 예정.
- **전체시장 단일 모집단(리드 확정)**: 업종 간 비교가능성 문제(은행 EV/EBITDA 무의미 등)는 인지된 v1 한계 — grouping seam만 확보, sector peer-group은 후속 2-7. **이 자체를 다시 지적하지 마.**
- **매크로 모집단=전체 역사(리드 확정)**: 롤링 윈도우 아님.
- **1~3분기 동일연도 look-ahead 잔여 리스크**: 2.1에서 defer된 공통 항목(실제 공시일 `available_at` 필요, 별도 스토리). 사업보고서(quarter=4)만 확정 배제.
- **날짜 String(10) 컨벤션**: 프로젝트 전체 defer(2.1 리뷰), as_of는 진입점 정규식 검증.
- **select-then-insert 동시성**: 전 저장소 공통 defer(v1 단일 프로세스).
- **3요소 전부 None → 행 미생성+삭제**: macro만으론 종목별 정보가 없어 all-null 행 방지(1-6 교훈). 의도됨.
- **검증**: pytest 153 passed(mna 17 신규, 기존 136 회귀 0).

## 출력 형식
`[High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정`. 없으면 "clean".
특히 답해줘: (1) `_percentile_rank`의 "(엄격히 작은 수)/(N-1), 자기 포함" 정의가 퇴화 케이스(전원 동일값·N=2·대량 동점)에서 스코어 의미를 왜곡하는지와 더 나은 대안(mid-rank 등)이 실익이 있는지, (2) corp_codes 부분집합 실행과 전체 실행이 다른 결과를 낳는 시나리오가 있는지(모집단은 항상 전체시장인데 놓친 구멍이 있나), (3) `latest_macro_percentile_basis`가 아주 오래된 마지막 관측값을 현재값으로 쓰는 staleness 문제가 실제 ECOS 월간 데이터에서 유의미한지.
