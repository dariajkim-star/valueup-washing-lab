"""다중조건 스크리닝 조회 저장소 (AD-2: SQL은 여기서만).

company 기준으로 valueup_score·mna_score를 (corp_code, as_of) outer join — 한쪽 엔진이
그 as_of에 실행되지 않았으면 그쪽 필드가 null로 드러난다(세대 혼합을 조인으로 감추지 않고
정직 노출). 두 스코어 테이블 모두 **읽기 전용**(writer는 각 엔진, AD-4/AD-10).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.orm import Session

from app.models import Company, MnaScore, OpacityScore, ValueupPlan, ValueupScore

# 정렬 허용 필드 화이트리스트(AD-6 `field`/`-field` 규약). 사용자 입력을 컬럼 객체로만
# 매핑 — 여기 없는 필드는 InvalidSortError(라우터가 400으로 변환). metrics.py 패턴의 ORM 판.
SORT_COLUMNS = {
    "execution_score": ValueupScore.execution_score,
    "mna_target_score": MnaScore.mna_target_score,
    "opacity_rank": OpacityScore.opacity_rank,
}


class InvalidSortError(ValueError):
    """sort 필드가 화이트리스트 밖 — 사용자 입력 오류(400).

    ValueError를 그대로 잡으면 pydantic ValidationError(ValueError 하위)까지 400
    INVALID_SORT로 세탁된다(GPT 리뷰 Med) — 전용 타입으로만 잡는다.
    """


def validate_sort(sort: str | None) -> None:
    """sort 입력의 순수 검증(DB 접근 없음). 서비스 진입 직후 호출 — 스코어 미적재
    short-circuit보다 먼저 실행돼야 빈 DB에서도 잘못된 sort가 400이다(GPT 리뷰 Med).
    빈 문자열·`-`단독도 화이트리스트 밖으로 거부(GPT 리뷰 Low — 생략(None)과 빈 입력 구분).
    """
    if sort is None:
        return
    field = sort[1:] if sort.startswith("-") else sort
    if not field or field not in SORT_COLUMNS:
        raise InvalidSortError(f"invalid sort field: {field!r}")


def latest_as_of(session: Session) -> str | None:
    """세 스코어 테이블 latest as_of 중 max(가장 최근 엔진 실행 시점). 셋 다 없으면 None.

    opacity_score가 빠지면 opacity만 실행된(또는 opacity가 가장 최근인) 세대가 서빙 기준일에서
    누락돼 스크리닝이 빈 결과를 낸다 — 3번째 join과 한 쌍으로 반드시 포함해야 한다.
    """
    v = session.scalar(select(func.max(ValueupScore.as_of)))
    m = session.scalar(select(func.max(MnaScore.as_of)))
    o = session.scalar(select(func.max(OpacityScore.as_of)))
    candidates = [x for x in (v, m, o) if x is not None]
    return max(candidates) if candidates else None


def _latest_metrics_map(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """corp별 look-ahead **부분 차단** 최신 지표(roe·pbr·ev_ebitda·debt_ratio) — 3.3 리뷰 반영.

    2.1/2.3/3.1과 동일한 사업보고서 배제 규칙 + Python dedupe(DISTINCT ON 회피, 이식성).
    **"안전"이 아니라 "부분 차단"인 이유(재리뷰 정정)**: 같은 해 사업보고서(quarter=4)만
    확정 배제 가능(항상 다음 해 공시). 1~3분기 보고서의 동일연도 시차는 실제 공시일
    (`available_at`) 데이터가 없어 차단 불가 — 명시적 과거 as_of 조회 시 그 해의 이후
    분기가 섞일 수 있다. 완전 해결은 공시일 수집 별도 스토리(deferred-work 2-1, 전 엔진·
    stats·screening 공통 한계 — 여기만 달력 휴리스틱을 넣으면 엔드포인트 간 규칙이 갈라짐).
    look-ahead 패턴 4번째 사용처 — 시그니처가 소비자마다 달라 공통화는 deferred.
    """
    as_of_year = int(as_of[:4])
    rows = session.execute(
        text(
            "SELECT corp_code, roe, pbr, ev_ebitda, debt_ratio FROM valuation_metrics "
            "WHERE year < :yr OR (year = :yr AND quarter < 4) "
            "ORDER BY corp_code, year DESC, quarter DESC"
        ),
        {"yr": as_of_year},
    ).mappings().all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["corp_code"] not in latest:  # 정렬상 corp별 첫 행 = 최신
            latest[row["corp_code"]] = dict(row)
    return latest


def _latest_market_cap_map(session: Session) -> dict[str, int | None]:
    """corp별 최신 시가총액(prices가 단일 원천, AD-9).

    뷰의 PBR과 동일하게 '전역 최신가' 컨벤션(1.7 known-limitation — 과거 as_of의
    point-in-time 시총은 기존 defer 그대로). 시총구간 필터 전용.
    """
    rows = session.execute(
        text("SELECT corp_code, market_cap FROM prices ORDER BY corp_code, date DESC")
    ).all()
    latest: dict[str, int | None] = {}
    for corp_code, market_cap in rows:
        if corp_code not in latest:
            latest[corp_code] = market_cap
    return latest


# 지표 범위 필터 정의: (파라미터 키, 지표 컬럼, 비교 방향). null 지표는 어느 범위에도
# 매칭되지 않는다(SQL 3치 논리와 동일 의미 — "산출 불가는 조건 판단 불가", 2.1 원칙).
_METRIC_FILTERS = (
    ("min_roe", "roe", "ge"),
    ("max_pbr", "pbr", "le"),
    ("max_ev_ebitda", "ev_ebitda", "le"),
    ("max_debt_ratio", "debt_ratio", "le"),
)


def _passes_metric_filters(m: dict[str, Any] | None, filters: dict[str, Any]) -> bool:
    for key, col, op in _METRIC_FILTERS:
        bound = filters.get(key)
        if bound is None:
            continue
        val = m.get(col) if m else None
        if val is None:  # 지표 없음/산출 불가 → 범위 필터 불통과(null 세탁 금지)
            return False
        if op == "ge" and val < bound:
            return False
        if op == "le" and val > bound:
            return False
    return True


def list_screening(
    session: Session, filters: dict[str, Any], page: int, size: int,
    sort: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """스크리닝 조회(2.6). 필터는 AND 조합, 범위 필터의 null은 SQL 3치 논리로 자연 배제
    ("산출 불가는 조건 매칭 불가"). buyback_executed=false는 `IS FALSE` — null(판단 불가)은
    true에도 false에도 안 걸린다(null 세탁 금지, 2.1 원칙).
    """
    as_of = filters["as_of"]
    conds: list[Any] = []
    if filters.get("corp_code") is not None:  # 3.4 상세화면 단건 조회용(정확일치)
        conds.append(Company.corp_code == filters["corp_code"])
    if filters.get("market") is not None:
        conds.append(Company.market == filters["market"])
    if filters.get("sector") is not None:
        conds.append(Company.sector.startswith(filters["sector"], autoescape=True))
    if filters.get("min_execution_score") is not None:
        conds.append(ValueupScore.execution_score >= filters["min_execution_score"])
    if filters.get("max_execution_score") is not None:
        conds.append(ValueupScore.execution_score <= filters["max_execution_score"])
    if filters.get("min_mna_score") is not None:
        conds.append(MnaScore.mna_target_score >= filters["min_mna_score"])
    if filters.get("max_mna_score") is not None:
        conds.append(MnaScore.mna_target_score <= filters["max_mna_score"])
    # 불투명도 범위 필터(AC2) — washing_only를 대체한다. washing_flag는 실측 True=0인
    # '켜질 수 없는 경고등'이라 그 토글은 항상 빈 결과를 냈다(죽은 필터). 고의 판정 대신
    # 격차로 거른다: "이 공시 수준으론 밸류 신뢰 불가"를 순위 상위로 뽑는다.
    if filters.get("min_opacity_rank") is not None:
        conds.append(OpacityScore.opacity_rank >= filters["min_opacity_rank"])
    if filters.get("max_opacity_rank") is not None:
        conds.append(OpacityScore.opacity_rank <= filters["max_opacity_rank"])
    if filters.get("buyback_executed") is not None:
        conds.append(ValueupScore.buyback_executed.is_(filters["buyback_executed"]))

    # 지표 범위 필터(3.3 리뷰 반영, AC2): 뷰(valuation_metrics)는 ORM 매핑이 없어 조인
    # 대신 2단계 — 통과 corp_code 집합을 Python에서 구해 IN 조건으로 주입. COUNT·정렬·
    # 페이지네이션은 SQL에 그대로 남는다(페이지 후 필터링 오류 방지).
    metrics_map = _latest_metrics_map(session, as_of)
    if any(filters.get(k) is not None for k, _, _ in _METRIC_FILTERS):
        passing = [
            code for code in metrics_map
            if _passes_metric_filters(metrics_map.get(code), filters)
        ]
        conds.append(Company.corp_code.in_(passing))
    # 시총구간 필터: prices 최신 시총(AD-9 단일 원천). null 시총은 불통과.
    if filters.get("min_market_cap") is not None or filters.get("max_market_cap") is not None:
        mcap = _latest_market_cap_map(session)
        lo, hi = filters.get("min_market_cap"), filters.get("max_market_cap")
        passing_mcap = [
            code for code, v in mcap.items()
            if v is not None and (lo is None or v >= lo) and (hi is None or v <= hi)
        ]
        conds.append(Company.corp_code.in_(passing_mcap))

    base = (
        select(Company, ValueupScore, MnaScore, OpacityScore, ValueupPlan.body_signal)
        .select_from(Company)
        .join(
            ValueupScore,
            and_(ValueupScore.corp_code == Company.corp_code,
                 ValueupScore.as_of == as_of),
            isouter=True,
        )
        .join(
            MnaScore,
            and_(MnaScore.corp_code == Company.corp_code, MnaScore.as_of == as_of),
            isouter=True,
        )
        .join(
            OpacityScore,
            and_(OpacityScore.corp_code == Company.corp_code,
                 OpacityScore.as_of == as_of),
            isouter=True,
        )
        # 근거 공시의 본문 신호(0018) — 선택 규칙을 재현하지 않고 source_plan_id(0016)로
        # 조인만 한다. 목록의 '순위 불가'가 "부실 공시"인지 "타 지표로 공시(other_metric)"
        # 인지 구분하기 위한 것(파티 결정 2026-07-29: 판정 대신 사실 표기).
        .join(
            ValueupPlan,
            ValueupPlan.plan_id == ValueupScore.source_plan_id,
            isouter=True,
        )
        # 세 스코어 모두 없는 종목 제외 — 회사정보만 있는 노이즈 행 방지
        .where(
            or_(
                ValueupScore.id.is_not(None),
                MnaScore.id.is_not(None),
                OpacityScore.id.is_not(None),
            ),
            *conds,
        )
    )

    total = session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0

    order = _order_by(sort)
    rows = session.execute(
        base.order_by(*order).limit(size).offset((page - 1) * size)
    ).all()

    items = []
    for company, vs, ms, os, body_signal in rows:
        m = metrics_map.get(company.corp_code)
        items.append({
            "corp_code": company.corp_code,
            "corp_name": company.corp_name,
            "market": company.market,
            "sector": company.sector,
            "as_of": as_of,
            # 핵심지표(AC3, 3.3 리뷰 반영): look-ahead 부분 차단 최신 지표(재리뷰 정정 —
            # 같은 해 사업보고서만 확정 배제, 1~3분기 동일연도 잔여 리스크는 기존 defer).
            # 없으면 null.
            "roe": m.get("roe") if m else None,
            "pbr": m.get("pbr") if m else None,
            # has_* 플래그: "row 없음(엔진 미실행)"과 "row는 있으나 전부 null(엄격
            # 게이팅으로 산출 불가)"을 구분(GPT 리뷰 Med — 없으면 소비자가 식별 불가)
            "has_valueup_score": vs is not None,
            "has_mna_score": ms is not None,
            "has_opacity_score": os is not None,
            "execution_score": vs.execution_score if vs else None,
            # 점수가 **무엇을 근거로** 매겨졌는지(5-1). 공시한 약속만으로 채점하므로
            # 가중치 기반이 종목마다 다르다 — 숨기면 기준이 다른 점수를 나란히 비교하게 된다.
            "score_basis": vs.score_basis if vs else None,
            "washing_flag": vs.washing_flag if vs else None,
            "buyback_status": vs.buyback_status if vs else None,
            # 소각 시점(0022) — 목록의 "최근 소각" 배지가 약속과의 관계를 말할 수 있게.
            "buyback_timing": vs.buyback_timing if vs else None,
            "buyback_executed": vs.buyback_executed if vs else None,
            "mna_target_score": ms.mna_target_score if ms else None,
            "population_basis": ms.population_basis if ms else None,
            # opacity_rank 계약: null=순위 불가(0/최투명 표시 금지). opacity_basis는 순위의
            # 모집단 식별 — 기준이 다른 순위를 같은 척도로 비교하지 않게 순위와 함께 전달.
            "opacity_rank": os.opacity_rank if os else None,
            "opacity_count": os.opacity_count if os else None,
            "opacity_basis": os.opacity_basis if os else None,
            # '순위 불가'의 이유 구분용(0018 신호). 상세(plan_body_signal)와 같은 값.
            "plan_body_signal": body_signal,
        })
    return items, total


def _disclosed_axis_count_sql() -> Any:
    """score_basis("roe+buyback+payout")의 축 수를 SQL로 센다 — '+' 개수 + 1.

    execution_score **동점을 깨는 2차 키**로만 쓴다(정렬 키이지 점수가 아니다).
    null/빈 문자열은 0축.
    """
    basis = func.coalesce(ValueupScore.score_basis, "")
    return case(
        (basis == "", 0),
        else_=func.length(basis) - func.length(func.replace(basis, "+", "")) + 1,
    )


def _order_by(sort: str | None) -> list[Any]:
    """sort=`field`/`-field`를 화이트리스트로 안전 변환(null last 명시 + corp_code 안정 정렬).

    기본 정렬은 corp_code — 스크리닝은 양방향(워싱↔M&A 후보)이라 임의 기본 정렬로
    의미를 암시하지 않는다. 입력 검증은 validate_sort가 서비스 진입에서 선수행하지만,
    여기서도 방어적으로 재검증(단일 진입점 우회 대비).
    `is None`(truthiness 아님): 빈 문자열은 기본 정렬이 아니라 검증 오류다.

    ■ execution_score 동점은 **공시 축 수**로 깬다 (파티 결정 2026-07-31)
        표본을 33 → 359로 늘린 뒤 실측: 채점된 84종목 중 **49개(58%)가 100점 동점**이고,
        그중 43개가 단일축이다(payout 단독 21 · buyback 단독 20). 세 축을 다 지킨
        기아가 자사주 하나만 공시한 20개와 같은 자리에 놓인다.
        척도가 상단에서 포화됐으므로 표시 순서를 corp_code(무의미)에 맡기지 않고,
        "같은 100점이라도 더 많이 약속하고 지킨 쪽이 위"로 깬다. 점수 계산은 그대로다 —
        채점 계약을 바꾸지 않고 정렬만 바꾼다(score_basis는 이미 서빙 중이라 화면이
        그 이유를 설명할 수 있다).
        33종목 때 진단("자사주가 이진축이라 문제")도 이 실측으로 갱신됐다: payout 단독이
        더 많다 — 이진축 특유의 문제가 아니라 **단일축 채점 자체**가 만점을 남발한다.
    """
    if sort is None:
        return [Company.corp_code.asc()]
    validate_sort(sort)
    desc = sort.startswith("-")
    field = sort[1:] if desc else sort
    col = SORT_COLUMNS[field]
    direction = col.desc() if desc else col.asc()
    keys: list[Any] = [col.is_(None), direction]
    if field == "execution_score":
        keys.append(_disclosed_axis_count_sql().desc())
    keys.append(Company.corp_code.asc())  # 안정 정렬(마지막)
    return keys
