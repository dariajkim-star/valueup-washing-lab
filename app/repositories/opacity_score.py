"""opacity_score 배치 입력 조회 + 멱등 upsert 저장소 (AD-2: SQL은 여기서만).

opacity_engine(app/analysis/opacity_engine.py)의 유일한 DB 접근 지점. mna_score.py와 동형 —
opacity_rank도 cross-sectional 백분위라 종목 루프 안에서 단건 쿼리하면 N+1이자 설계 오류
(한 종목의 순위가 전체 분포에 의존). 전체 모집단을 배치로 한 번에 가져온다.

look-ahead: valueup_plan은 disclosure_date(접수일)만 있으므로 `disclosure_date <= as_of`로
그 시점 이후 공시를 배제(valueup_score.latest_valueup_plan과 동일 규칙). 동일 disclosure_date
tie-break은 plan_id 내림차순("나중에 적재된 것"을 결정적으로 채택 — 정정공시 등).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.analysis.plan_selection import choose_plan, merge_attachment

from app.models import Company, OpacityScore, PlanAttachment


def list_all_corp_codes(session: Session) -> list[str]:
    """전 종목 corp_code 목록(run()의 corp_codes 기본값)."""
    return list(session.scalars(select(Company.corp_code)).all())


def all_company_sectors(session: Session) -> dict[str, str | None]:
    """전 종목 corp_code → sector(DART induty_code). 버킷 택소노미 입력(mna와 공용 규약)."""
    rows = session.execute(select(Company.corp_code, Company.sector)).all()
    return {code: sector for code, sector in rows}


def all_latest_plans(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """전 종목의 as_of 이전(포함) 최신 valueup_plan 1건(배치).

    corp_code → {target_roe, target_payout_ratio, target_total_return_ratio,
    period_start, buyback_planned}. opacity_axes(목표 미공시 판정)와 is_unrankable(본문 전무
    판정)의 입력 전부를 담는다. raw_text는 참조 검사 폐기(2026-07-28)로 더는 읽지 않는다.

    corp별 최신 1행을 Python에서 선택(정렬된 결과 첫 등장 유지 — SQLite/PostgreSQL 양쪽에서
    동일 동작). tie-break은 disclosure_date DESC → plan_id DESC(latest_valueup_plan과 동일).
    """
    stmt = (
        text(
            "SELECT corp_code, plan_id, disclosure_date, target_roe, "
            "target_payout_ratio, target_total_return_ratio, period_start, "
            "buyback_planned, body_signal, body_reference_date FROM valueup_plan "
            "WHERE disclosure_date <= :as_of "
            "ORDER BY corp_code, disclosure_date DESC, plan_id DESC"
        )
    )
    rows = session.execute(stmt, {"as_of": as_of}).mappings().all()
    # corp별 후보를 최신순 그대로 모아 choose_plan에 넘긴다(2026-07-29 폴백 규칙).
    # 이전엔 "corp별 첫 행 = 최신"만 취했는데, 그러면 최신이 표지 통지문(0축)인 종목이
    # 이미 파싱해둔 과거 목표를 두고도 is_unrankable로 빠졌다(하나금융·LG화학·삼성화재).
    # 선택 규칙은 gap쪽(latest_valueup_plan)과 **같은 함수**를 써야 한다 — 두 엔진이 서로
    # 다른 공시를 근거로 삼으면 "목표는 보이는데 순위는 불가"인 자기모순이 생긴다.
    # 첨부 목표를 같은 공시에 합친다(gap쪽과 동일 — 두 엔진이 다른 목표를 보면
    # "점수는 있는데 순위는 불가" 같은 자기모순이 생긴다).
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
        }
        for a in session.scalars(select(PlanAttachment)).all()
    }

    by_corp: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        merged = merge_attachment(dict(row), attachments.get(row["plan_id"]))
        by_corp.setdefault(row["corp_code"], []).append(merged)

    latest: dict[str, dict[str, Any]] = {}
    for code, candidates in by_corp.items():
        choice = choose_plan(candidates)
        if choice is not None:
            row = choice.plan
            latest[code] = {
                "target_roe": row["target_roe"],
                "target_payout_ratio": row["target_payout_ratio"],
                "target_total_return_ratio": row["target_total_return_ratio"],
                "period_start": row["period_start"],
                "buyback_planned": row["buyback_planned"],
            }
    return latest


def upsert_opacity_score(session: Session, rec: dict[str, Any]) -> OpacityScore:
    """(corp_code, as_of) 자연키 기준 opacity_score upsert.

    mna_score와 동일 정책: 권위 있는 전체 재계산 결과이므로 null 포함 전체 교체 +
    `rec[field]` 직접 인덱싱(키 누락은 프로그래밍 오류 → KeyError로 즉시 노출).
    """
    stmt = select(OpacityScore).where(
        OpacityScore.corp_code == rec["corp_code"], OpacityScore.as_of == rec["as_of"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = OpacityScore(corp_code=rec["corp_code"], as_of=rec["as_of"])
        session.add(obj)
    for field in ("opacity_rank", "opacity_count", "opacity_basis"):
        setattr(obj, field, rec[field])
    return obj


def delete_opacity_score(session: Session, corp_code: str, as_of: str) -> None:
    """근거(순위 가능한 계획)를 잃은 (corp_code, as_of)의 오래된 score 정리(reconciliation
    패턴). 계획 없음·본문 전무·유효 peer<2로 순위 불가한 종목이 대상. 없으면 no-op(멱등)."""
    stmt = select(OpacityScore).where(
        OpacityScore.corp_code == corp_code, OpacityScore.as_of == as_of,
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is not None:
        session.delete(obj)


# ── 서빙 조회 ────────────────────────────────────────────────────────────────
# 위쪽은 opacity_engine 전용 배치 입력·upsert, 아래는 읽기 전용(쓰기는 엔진만, AD-10).


def latest_as_of(session: Session) -> str | None:
    """opacity_score의 최신 as_of. 없으면 None."""
    return session.scalar(select(func.max(OpacityScore.as_of)))
