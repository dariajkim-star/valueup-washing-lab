"""valueup_plan 멱등 upsert 저장소.

수집 경로 전용(서빙 아님). 자연키 (corp_code, disclosure_date) 기준으로
존재하면 갱신, 없으면 삽입 → 재실행 안전(AD-7).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ValueupPlan

_TARGET_FIELDS = (
    "target_roe",
    "target_payout_ratio",
    "target_total_return_ratio",
    "target_pbr",
    "period_start",
    "period_end",
    "buyback_planned",
    # 본문 신호(0018)는 목표와 **같은 원문에서 같은 시점에** 도출되므로 함께 전체 교체한다.
    # 파서를 고쳐 축이 잡히면 신호도 other_metric → axis_targets로 따라 바뀌어야 한다.
    "body_signal",
    "body_reference_date",
)


def upsert_valueup_plan(session: Session, rec: dict) -> ValueupPlan:
    """(corp_code, disclosure_date) 자연키 기준 valueup_plan upsert.

    여기 도달한 rec은 **유효 문서를 성공적으로 파싱한 권위 있는 결과**다(문서 fetch 실패 건은
    어댑터 fetch에서 걸러져 오지 않음). 따라서 목표 필드를 **null 포함 전체 교체**한다 —
    이렇게 해야 정규식을 개선해 재파싱할 때 과거 오탐 non-null 값(예: PBR 2027)이 null로
    정정된다(None-safe였다면 옛 오값이 영구 잔존). raw_text도 새 유효 원문으로 교체.
    """
    stmt = select(ValueupPlan).where(
        ValueupPlan.corp_code == rec["corp_code"],
        ValueupPlan.disclosure_date == rec["disclosure_date"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = ValueupPlan(
            corp_code=rec["corp_code"], disclosure_date=rec["disclosure_date"]
        )
        session.add(obj)
    for field in _TARGET_FIELDS:
        setattr(obj, field, rec.get(field))  # null 포함 전체 교체
    obj.raw_text = rec.get("raw_text")
    # 출처(0015): 접수번호는 **null로 덮어쓰지 않는다.** 목표 필드와 규칙이 다른 이유 —
    # 목표는 재파싱 결과가 권위(오탐 정정이 목적)지만, rcept_no는 파싱 산물이 아니라
    # 그 문서의 신원이다. 이미 아는 신원을 모른다고 되돌릴 이유가 없다.
    if rec.get("rcept_no"):
        obj.rcept_no = rec["rcept_no"]
    return obj
