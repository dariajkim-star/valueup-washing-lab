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

from app.models import Company, OpacityScore


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
    period_start, buyback_planned, raw_text}. opacity_axes(목표 미공시 판정)와
    is_cover_notice(raw_text 첨부 참조 여부)의 입력 전부를 담는다.

    corp별 최신 1행을 Python에서 선택(정렬된 결과 첫 등장 유지 — SQLite/PostgreSQL 양쪽에서
    동일 동작). tie-break은 disclosure_date DESC → plan_id DESC(latest_valueup_plan과 동일).
    """
    stmt = (
        text(
            "SELECT corp_code, target_roe, target_payout_ratio, "
            "target_total_return_ratio, period_start, buyback_planned, raw_text "
            "FROM valueup_plan "
            "WHERE disclosure_date <= :as_of "
            "ORDER BY corp_code, disclosure_date DESC, plan_id DESC"
        )
    )
    rows = session.execute(stmt, {"as_of": as_of}).mappings().all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row["corp_code"]
        if code not in latest:  # 정렬상 corp별 첫 행 = 최신
            latest[code] = {
                "target_roe": row["target_roe"],
                "target_payout_ratio": row["target_payout_ratio"],
                "target_total_return_ratio": row["target_total_return_ratio"],
                "period_start": row["period_start"],
                "buyback_planned": row["buyback_planned"],
                "raw_text": row["raw_text"],
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
    패턴). 계획 없음·표지 통지문·유효 peer<2로 순위 불가한 종목이 대상. 없으면 no-op(멱등)."""
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
