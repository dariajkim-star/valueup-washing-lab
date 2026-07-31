"""valueup_score 입력 조회 + 멱등 upsert 저장소 (AD-2: SQL은 여기서만).

gap_engine(app/analysis/gap_engine.py)의 유일한 DB 접근 지점. 세 가지 읽기(공시 목표·
실적 지표·자사주 원천)와 한 가지 쓰기(스코어 upsert)로 구성. gap_engine 자체는 dict/스칼라만
다루고 SQL을 직접 실행하지 않는다(AD-2).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session

from app.analysis.plan_selection import choose_plan, merge_attachment
from app.models import (
    Company,
    Financial,
    PlanAttachment,
    ValueupPlan,
    ValueupScore,
)


def list_all_corp_codes(session: Session) -> list[str]:
    """전 종목 corp_code 목록(run()의 corp_codes 기본값). SQL은 여기서만(AD-2)."""
    return list(session.scalars(select(Company.corp_code)).all())


def latest_valueup_plan(
    session: Session, corp_code: str, as_of: str
) -> dict[str, Any] | None:
    """as_of 이전(포함) 최신 valueup_plan 1건. 여러 공시 중 as_of 직전 최신 것을 target으로 채택
    (2026-07-10 리드 결정 A: 기간-포함 판정 대신 단순·재현 가능한 규칙).

    동일 disclosure_date(원공시+정정공시 등) tie-break은 plan_id 내림차순(코드리뷰 Med,
    GPT) — 접수번호 등 진짜 우선순위 필드가 없어 "나중에 적재된 것"을 결정적으로 채택.
    """
    stmt = (
        select(ValueupPlan)
        .where(
            ValueupPlan.corp_code == corp_code,
            ValueupPlan.disclosure_date <= as_of,
        )
        .order_by(ValueupPlan.disclosure_date.desc(), ValueupPlan.plan_id.desc())
        # limit(1) 제거(2026-07-29): 최신이 표지 통지문(0축)이면 그 이전 공시로 내려가야
        # 하므로 후보 전체가 필요하다. 종목당 공시는 실측 최대 5건이라 비용은 무시할 만하다.
    )
    # 첨부(계획서 PDF)에서 읽은 목표를 같은 공시의 본문 목표와 합친다(0017·0019).
    # 공시 본문이 "첨부된 계획을 참고하라"인 경우 실물은 첨부이므로, 합치지 않으면
    # 우리가 이미 파싱해 둔 목표를 두고도 그 공시를 0축으로 취급하게 된다.
    attachments = {
        a.plan_id: {
            "target_roe": a.target_roe,
            "target_payout_ratio": a.target_payout_ratio,
            "target_total_return_ratio": a.target_total_return_ratio,
            "target_pbr": a.target_pbr,
            "period_start": a.period_start,
            "period_end": a.period_end,
            "buyback_planned": a.buyback_planned,
            "parse_error": a.parse_error,
            "needs_review": a.needs_review,
        }
        for a in session.scalars(
            select(PlanAttachment).where(PlanAttachment.corp_code == corp_code)
        ).all()
    }

    candidates = [
        {
            "plan_id": o.plan_id,
            "disclosure_date": o.disclosure_date,
            "rcept_no": o.rcept_no,
            "target_roe": o.target_roe,
            "target_payout_ratio": o.target_payout_ratio,
            "target_total_return_ratio": o.target_total_return_ratio,
            "target_pbr": o.target_pbr,  # 계산 미사용, 참고 보관만(리드 결정)
            "period_start": o.period_start,
            "period_end": o.period_end,
            "buyback_planned": o.buyback_planned,
            # 선택 규칙이 재공시를 건너뛰려면 신호가 후보에 실려야 한다(0018)
            "body_signal": o.body_signal,
            "body_reference_date": o.body_reference_date,
        }
        for o in session.scalars(stmt).all()
    ]
    candidates = [
        merge_attachment(c, attachments.get(c["plan_id"])) for c in candidates
    ]
    choice = choose_plan(candidates)
    if choice is None:
        return None
    # 고른 공시의 신원(plan_id·공시일·접수번호)을 목표값과 **함께** 돌려준다 —
    # 엔진이 그것을 valueup_score에 저장해야 화면이 실제 근거를 출처로 표시할 수 있다.
    return {**choice.plan, "used_fallback": choice.used_fallback}


def latest_metrics(session: Session, corp_code: str, as_of: str) -> dict[str, Any] | None:
    """as_of 이전 최신 (year,quarter) valuation_metrics 행. look-ahead 부분 차단(코드리뷰 High,
    GPT): 같은 연도의 **사업보고서(quarter=4)는 그 해 안에 공시될 수 없음**(결산 후 통상 90일
    이내 = 다음 해)이므로 무조건 제외 — `year<as_of_year OR (year=as_of_year AND quarter<4)`.
    1~3분기 보고서의 동일연도 내 공시시차는 실제 공시일 데이터가 없어 잔여 리스크로 defer
    (deferred-work.md 2-1 섹션). AD-1: 뷰가 계산한 값을 읽기만.
    """
    as_of_year = int(as_of[:4])
    row = session.execute(
        text(
            "SELECT roe, payout_ratio, total_return_ratio FROM valuation_metrics "
            "WHERE corp_code = :cc AND (year < :yr OR (year = :yr AND quarter < 4)) "
            "ORDER BY year DESC, quarter DESC LIMIT 1"
        ),
        {"cc": corp_code, "yr": as_of_year},
    ).mappings().one_or_none()
    return dict(row) if row is not None else None


def latest_financial_buyback(
    session: Session, corp_code: str, as_of: str
) -> dict[str, Any] | None:
    """as_of 이전 최신 (year,quarter) financials의 buyback 수량 필드.
    look-ahead 부분 차단은 latest_metrics와 동일 규칙(사업보고서 동일연도 제외)."""
    as_of_year = int(as_of[:4])
    stmt = (
        select(Financial)
        .where(
            Financial.corp_code == corp_code,
            or_(
                Financial.year < as_of_year,
                and_(Financial.year == as_of_year, Financial.quarter < 4),
            ),
        )
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
    `rec[field]`(직접 인덱싱, 코드리뷰 Med, GPT): 키 누락은 프로그래밍 오류이므로
    `.get()`으로 조용히 None 넘기지 않고 KeyError로 즉시 드러낸다.
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
        "target_roe", "actual_roe", "roe_gap",
        "achievement_rate", "progress_rate", "execution_score", "washing_flag",
        "buyback_executed", "buyback_retired", "buyback_status", "score_basis",
        "excluded_axes", "source_plan_id",
    ):
        setattr(obj, field, rec[field])
    return obj


def latest_as_of(session: Session) -> str | None:
    """valueup_score의 최신 as_of(기본 조회 기준일, 2.4). 없으면 None."""
    from sqlalchemy import func

    return session.scalar(select(func.max(ValueupScore.as_of)))


def list_scores(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> tuple[list[dict[str, Any]], int]:
    """갭분석/워싱랭킹 서빙 조회(2.4). company 조인 + 필터 + execution_score 오름차순.

    null 정렬은 방언(SQLite NULLS FIRST/PG NULLS LAST 기본 차이)을 타지 않도록
    명시적 2단 키(`IS NULL` 우선순위 → 값)로 처리(1.7 defer 교훈). 동순위는 corp_code로
    안정 정렬(페이지네이션 결정성).
    """
    from sqlalchemy import func

    from app.models import Company

    conds = [ValueupScore.as_of == filters["as_of"]]
    if filters.get("corp_code") is not None:  # 3.4 상세화면 단건 조회용(정확일치)
        conds.append(Company.corp_code == filters["corp_code"])
    # `is not None`: 빈 문자열이 "필터 없음"으로 새지 않게(2-5 리뷰 패리티 — 1차 방어는
    # 라우터 min_length=1의 422)
    if filters.get("market") is not None:
        conds.append(Company.market == filters["market"])
    if filters.get("min_progress") is not None:
        conds.append(ValueupScore.progress_rate >= filters["min_progress"])
    if filters.get("washing_only"):
        conds.append(ValueupScore.washing_flag.is_(True))

    # 출처(0015→0016): 점수가 **어느 공시에서 나왔는지**를 함께 서빙한다. 지금까지 화면은
    # "목표 ROE 10%"만 보여주고 그 숫자가 2024년 공시인지 2026년 공시인지 말하지 않았다.
    #
    # 0016부터 **선택 규칙을 여기서 재현하지 않는다.** 엔진이 실제로 고른 공시를
    # valueup_score.source_plan_id에 기록하므로 조인만 하면 된다. 규칙(최신 우선 + 0축이면
    # 과거 폴백)이 엔진과 서빙 두 곳에 있으면 어긋나는 순간 화면이 **실제 근거가 아닌
    # 공시**를 출처로 표시하는데, 그건 출처 표기의 목적과 정확히 반대다.
    #
    # 그 종목의 **최신** 공시일도 함께 뽑는다 — 근거 공시가 최신이 아니면(=폴백) 화면이
    # 그 사실을 말해야 하기 때문. "2024-10-29 공시 기준"만 쓰면 사용자는 왜 최신이 아닌지
    # 모른다. 폴백했다는 사실 자체가 출처의 일부다.
    newest_disclosure = (
        select(func.max(ValueupPlan.disclosure_date))
        .where(
            ValueupPlan.corp_code == ValueupScore.corp_code,
            ValueupPlan.disclosure_date <= filters["as_of"],
        )
        .correlate(ValueupScore)
        .scalar_subquery()
        .label("newest_disclosure_date")
    )

    base = select(ValueupScore, Company, ValueupPlan, newest_disclosure).join(
        Company, Company.corp_code == ValueupScore.corp_code
    ).outerjoin(  # outer: 근거 기록이 없거나(0016 이전 채점분) 계획이 사라져도 행을 잃지 않는다
        ValueupPlan, ValueupPlan.plan_id == ValueupScore.source_plan_id
    ).where(*conds)

    total = session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0
    rows = session.execute(
        base.order_by(
            ValueupScore.execution_score.is_(None),  # null last(명시적)
            ValueupScore.execution_score.asc(),
            ValueupScore.corp_code.asc(),
        ).limit(size).offset((page - 1) * size)
    ).all()

    items = []
    for score, company, plan, newest_date in rows:
        items.append({
            # 출처(0015) — null 계약: plan_rcept_no가 null이면 "0015 이전 적재분"이라
            # 재수집 전까지 DART 원문으로 갈 수 없다는 뜻. 빈 문자열로 뭉개지 않는다.
            "plan_disclosure_date": plan.disclosure_date if plan else None,
            "plan_rcept_no": plan.rcept_no if plan else None,
            # 본문 신호(0018) — 축을 못 채웠을 때 **왜**인지. 화면이 "순위 불가"라고만
            # 말하면 LG엔솔(매출·EBITDA로 명확히 공시)이 부실 공시로 읽힌다.
            "plan_body_signal": plan.body_signal if plan else None,
            # 근거 공시가 그 종목의 최신이 아니면 폴백이다(최신 공시에 목표가 없어 이전
            # 공시로 내려간 경우). 파생값이라 저장하지 않고 서빙 시점에 판정한다.
            "plan_is_fallback": (
                plan is not None
                and newest_date is not None
                and plan.disclosure_date != newest_date
            ),
            "plan_newest_disclosure_date": newest_date,
            "corp_code": score.corp_code,
            "corp_name": company.corp_name,
            "market": company.market,
            "as_of": score.as_of,
            "target_roe": score.target_roe,
            "actual_roe": score.actual_roe,
            "roe_gap": score.roe_gap,
            "achievement_rate": score.achievement_rate,
            "progress_rate": score.progress_rate,
            "execution_score": score.execution_score,
            "washing_flag": score.washing_flag,
            "buyback_status": score.buyback_status,
            "score_basis": score.score_basis,
            "excluded_axes": score.excluded_axes,
            # 환원 축 투명화(2026-07-31) — 목표는 근거 공시에서, 실적은 **엔진과 같은
            # 선택 규칙**(latest_metrics: look-ahead 차단)으로 읽는다. 규칙이 갈리면
            # 화면 숫자와 점수가 어긋나 출처 표기의 목적이 무너진다.
            **_payout_axis(session, score.corp_code, score.as_of, plan),
        })
    return items, total


def _payout_axis(
    session: Session, corp_code: str, as_of: str, plan: ValueupPlan | None
) -> dict[str, Any]:
    """환원 축의 목표·실적·달성배율. 채점에 쓰인 축(총주주환원율 우선)을 그대로 따른다.

    달성배율에 **캡을 걸지 않는 것**이 이 함수의 요점이다. execution_score는 _axis_score가
    [0,1]로 clamp해 과달성을 지우는데(의도된 설계 — 과달성이 다른 축의 신용을 사지 못하게),
    그 결과 "목표를 낮게 잡고 초과한" 기업과 "야심찬 목표를 겨우 맞춘" 기업이 똑같이 100점이
    된다. 실측(표본 359)에서 payout 단독 100점 21개 중 16개가 자기 과거 실적보다 낮은
    목표였다. 점수는 건드리지 않고, 그 사실을 상세 화면이 말할 수 있게 원값을 함께 준다.
    """
    out: dict[str, Any] = {
        "target_payout_ratio": plan.target_payout_ratio if plan else None,
        "target_total_return_ratio": plan.target_total_return_ratio if plan else None,
        "actual_payout_ratio": None,
        "actual_total_return_ratio": None,
        "payout_achievement": None,
    }
    if plan is None:
        return out
    metrics = latest_metrics(session, corp_code, as_of)
    if metrics is None:
        return out
    out["actual_payout_ratio"] = metrics.get("payout_ratio")
    out["actual_total_return_ratio"] = metrics.get("total_return_ratio")
    # 채점과 같은 우선순위: 총주주환원율이 있으면 그쪽(더 포괄적인 약속)
    if plan.target_total_return_ratio:
        target, actual = plan.target_total_return_ratio, out["actual_total_return_ratio"]
    elif plan.target_payout_ratio:
        target, actual = plan.target_payout_ratio, out["actual_payout_ratio"]
    else:
        return out
    if actual is not None and target:
        out["payout_achievement"] = round(actual / target, 3)
    return out


def delete_valueup_score(session: Session, corp_code: str, as_of: str) -> None:
    """plan이 사라진 (corp_code, as_of)의 오래된 score를 정리(코드리뷰 High, GPT: 정합성
    reconciliation). gap_engine이 valueup_score의 유일 writer(AD-4)이므로 근거가 사라진
    행을 제거할 책임도 이 모듈에 있다. 없으면 no-op(멱등)."""
    stmt = select(ValueupScore).where(
        ValueupScore.corp_code == corp_code, ValueupScore.as_of == as_of,
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is not None:
        session.delete(obj)
