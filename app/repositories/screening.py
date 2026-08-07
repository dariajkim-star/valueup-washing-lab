"""다중조건 스크리닝 조회 저장소 (AD-2: SQL은 여기서만).

company 기준으로 valueup_score·mna_score를 (corp_code, as_of) outer join — 한쪽 엔진이
그 as_of에 실행되지 않았으면 그쪽 필드가 null로 드러난다(세대 혼합을 조인으로 감추지 않고
정직 노출). 두 스코어 테이블 모두 **읽기 전용**(writer는 각 엔진, AD-4/AD-10).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.orm import Session

from app.analysis import lookahead
# 판정은 순수 모듈에서 직접 가져온다 — opacity_engine은 repository를 임포트하는
# 배선 층이라 서빙에서 부르면 순환이 난다(2026-08-07 실제로 났다).
from app.analysis.plan_signals import plan_reason_row, unrankable_reason
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


def _lowest_own_gap_map(session: Session, as_of: str) -> dict[str, float]:
    """corp별 **가장 낮은 자기과거 격차**(%p) — 야심도의 목록판(P1-7, 뷰 0024).

    "만점 70건 중 40건이 자기 과거보다 낮은 목표"인데 목록에서 구분되지 않아, 그 사실을
    찾으려면 상세를 70번 열어야 했다. 그래서 목록으로 올린다.

    **점수가 아니라 사실이다.** 공시한 축들 중 가장 낮은 격차 하나를 그대로 준다 —
    "야심도 낮음" 같은 등급으로 압축하지 않는다(P1-7 리드 결정 B).

    `plan_own_gap`은 뷰라 ORM 매핑이 없으므로 valuation_metrics 필터와 같은 2단계를 쓴다.
    **선택 규칙은 재현하지 않고 `source_plan_id`로 조인만 한다**(0016 이래의 계약) —
    어떤 공시가 근거인지는 plan_selection 한 곳만 정한다.

    비교할 과거가 없는 기업은 **맵에 없다**(0이 아니다). 없는 것을 "격차 0"으로 채우면
    잴 수 없는 기업이 "자기 과거만큼은 약속한 기업"으로 보인다.
    """
    rows = session.execute(
        text(
            "SELECT vs.corp_code, MIN(g.own_gap) FROM valueup_score vs "
            "JOIN plan_own_gap g ON g.plan_id = vs.source_plan_id "
            "WHERE vs.as_of = :a AND g.own_gap IS NOT NULL "
            "GROUP BY vs.corp_code"
        ),
        {"a": as_of},
    ).all()
    return {code: gap for code, gap in rows}


def _latest_metrics_map(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """corp별 look-ahead 차단 최신 지표(roe·pbr·ev_ebit·debt_ratio·환원율 2종).

    차단 규칙은 **`app/analysis/lookahead.py` 단일 정의처**를 부른다(0029 이관).
    실제 공시일(`available_at`, 사업보고서 rcept_dt)을 아는 행은 그 날짜로 판정하고,
    미수집 행만 기존 연도 휴리스틱으로 폴백한다. 커버리지 706/706(2026-08-04 수집).
    corp별 최신행 선택은 정렬 후 Python dedupe(DISTINCT ON 회피, 이식성).
    """
    rows = session.execute(
        text(
            "SELECT corp_code, roe, pbr, ev_ebit, debt_ratio, total_return_ratio, "
            "retired_return_ratio FROM valuation_metrics "
            f"WHERE {lookahead.sql_where()} "
            "ORDER BY corp_code, year DESC, quarter DESC"
        ),
        lookahead.params(as_of),
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
    ("max_ev_ebit", "ev_ebit", "le"),
    ("max_debt_ratio", "debt_ratio", "le"),
    # '매입만·소각 0' 필터(2026-08-04)의 임계 짝 — buyback_status와 조합해 쓴다.
    # 임계값 자체는 화면 다이얼 소유(7-28 임계 소유권 전례), 백엔드는 범위 필터만 준다.
    ("min_total_return", "total_return_ratio", "ge"),
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
    # '매입만·소각 0' 필터(2026-08-04, John): buyback_status 정확일치. 새 점수를 만들지
    # 않는다 — 이미 서빙 중인 사실(status)과 총환원율(min_total_return, _METRIC_FILTERS)의
    # 교집합이다. 정확일치라 status가 null(엔진 미실행)인 행은 어느 값에도 매칭되지 않고,
    # 'unknown'(판단 불가)은 명시적으로 그 값을 골랐을 때만 나온다 — null 세탁 없음.
    if filters.get("buyback_status") is not None:
        conds.append(ValueupScore.buyback_status == filters["buyback_status"])

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
    # 야심도 필터(P1-7): "자기 과거보다 낮은 목표"로 거른다. max_own_gap=0이면
    # 격차가 0 이하인 기업 — 즉 하던 것만큼도 약속하지 않은 기업만 남는다.
    # 기준선이 없는 기업은 맵에 없어 자연히 빠진다("산출 불가는 조건 매칭 불가",
    # 범위 필터 전반의 기존 계약과 같다 — null을 '통과'로도 '탈락'으로도 세탁하지 않는다).
    own_gap_map = _lowest_own_gap_map(session, as_of)
    if filters.get("max_own_gap") is not None:
        thr = filters["max_own_gap"]
        conds.append(
            Company.corp_code.in_([c for c, g in own_gap_map.items() if g <= thr])
        )

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
        select(Company, ValueupScore, MnaScore, OpacityScore, ValueupPlan)
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
    for company, vs, ms, os, plan in rows:
        body_signal = plan.body_signal if plan else None
        # 순위 불가의 **사유**(6.4/FR-15). 순위 가능하면 None이므로 화면은 이 값이
        # 있을 때만 말한다. 계획 엔티티를 통째로 받는 비용은 페이지 크기(<=100)에
        # 묶여 있고, 그 대가로 판정이 `unrankable_reason` **한 곳**에서만 난다.
        reason = unrankable_reason(plan_reason_row(plan)) if plan else None
        m = metrics_map.get(company.corp_code)
        items.append({
            "corp_code": company.corp_code,
            "corp_name": company.corp_name,
            "market": company.market,
            "sector": company.sector,
            "as_of": as_of,
            # 핵심지표(AC3): look-ahead 차단 최신 지표. 실제 공시일 기준(0029).
            # 없으면 null.
            "roe": m.get("roe") if m else None,
            "pbr": m.get("pbr") if m else None,
            # 총환원율 — '매입만·소각 0' 필터의 짝. 필터가 왜 걸렸는지 화면이 말하게 한다.
            "total_return_ratio": m.get("total_return_ratio") if m else None,
            # 소각 기준 환원율(0028) — 매입 기준과 나란히 서빙해 두 시선의 차이가
            # 한 행에서 보이게 한다(그 차이가 곧 '매입만 한 기업' 신호).
            "retired_return_ratio": m.get("retired_return_ratio") if m else None,
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
            # 순위 불가의 사유(6.4) — undisclosed(회사가 안 냈다·신호) /
            # unreadable(본문 밖에 있다·우리 한계) / unstated(근거 없음·판정 보류).
            "unrankable_reason": reason,
            # 목표의 야심도 — 공시한 축 중 자기 과거 대비 가장 낮은 격차(%p, P1-7).
            # 음수 = 하던 것보다 낮게 약속. null = 비교할 과거 실적 없음(0이 아니다).
            "lowest_own_gap": own_gap_map.get(company.corp_code),
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
