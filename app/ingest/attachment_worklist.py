"""무엇을 받아야 하는가 — 첨부가 필요한 공시 목록 출력.

실행: python -m app.ingest.attachment_worklist

취득이 수동이므로(DART robots.txt — attachment.py 모듈 문서 참조), 사람이 **무엇을·어디서·
어떤 이름으로** 받아야 하는지 정확히 알아야 한다. 그 목록을 코드가 만든다 — 사람이
DB를 뒤져 대상을 고르게 하면 그게 진짜 수작업이 된다.

대상 우선순위:
  1. 순위 불가(4축 전무) — 첨부 없이는 살릴 방법이 없는 종목. 여기가 첨부의 본래 목적.
  2. 부분 공시(1~3축) — 첨부에 나머지가 있을 수 있다.
이미 첨부를 파싱한 공시는 제외한다.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.analysis.plan_selection import choose_plan, disclosed_axis_count
from app.db import SessionLocal
from app.models import Company, PlanAttachment, ValueupPlan

_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"


def build_worklist(session, include_partial: bool = False) -> list[dict]:
    plans = session.scalars(
        select(ValueupPlan).order_by(
            ValueupPlan.corp_code,
            ValueupPlan.disclosure_date.desc(),
            ValueupPlan.plan_id.desc(),
        )
    ).all()
    names = dict(session.execute(select(Company.corp_code, Company.corp_name)).all())
    done = {
        pid for (pid,) in session.execute(
            select(PlanAttachment.plan_id).where(PlanAttachment.parse_error.is_(None))
        ).all()
    }

    by_corp: dict[str, list[ValueupPlan]] = {}
    for p in plans:
        by_corp.setdefault(p.corp_code, []).append(p)

    out: list[dict] = []
    for corp_code, candidates in by_corp.items():
        # 엔진과 같은 선택 규칙 — 실제 채점 근거가 되는 공시를 대상으로 삼아야 의미가 있다.
        rows = [
            {
                "plan_id": p.plan_id, "disclosure_date": p.disclosure_date,
                "rcept_no": p.rcept_no, "target_roe": p.target_roe,
                "target_payout_ratio": p.target_payout_ratio,
                "target_total_return_ratio": p.target_total_return_ratio,
                "period_start": p.period_start, "buyback_planned": p.buyback_planned,
            }
            for p in candidates
        ]
        choice = choose_plan(rows)
        if choice is None:
            continue
        chosen = choice.plan
        axes = disclosed_axis_count(chosen)
        if chosen["plan_id"] in done:
            continue
        if axes == 0:
            priority = 1
        elif include_partial and axes < 4:
            priority = 2
        else:
            continue
        rcept = chosen["rcept_no"]
        out.append({
            "priority": priority,
            "corp_code": corp_code,
            "corp_name": names.get(corp_code, "?"),
            "disclosure_date": chosen["disclosure_date"],
            "rcept_no": rcept,
            "axes": axes,
            "url": _VIEWER.format(rcept) if rcept else None,
            "save_as": (
                f"{rcept}.pdf" if rcept
                else f"{corp_code}_{chosen['disclosure_date']}.pdf"
            ),
        })
    out.sort(key=lambda r: (r["priority"], r["corp_name"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="첨부가 필요한 공시 목록")
    ap.add_argument("--all", action="store_true",
                    help="부분 공시(1~3축) 종목도 포함")
    args = ap.parse_args()

    with SessionLocal() as session:
        rows = build_worklist(session, include_partial=args.all)

    if not rows:
        print("받아야 할 첨부가 없습니다.")
        return 0

    print(f"첨부가 필요한 공시 {len(rows)}건 — attachments/ 에 아래 이름으로 저장하세요.\n")
    for r in rows:
        tag = "순위 불가" if r["priority"] == 1 else f"부분 공시({r['axes']}/4축)"
        print(f"[{tag}] {r['corp_name']} ({r['corp_code']}) · {r['disclosure_date']} 공시")
        if r["url"]:
            print(f"   열기:  {r['url']}")
        else:
            print("   열기:  접수번호 미보유 — 상세 화면의 '업데이트'로 재수집 후 다시 실행")
        print(f"   저장:  attachments/{r['save_as']}\n")
    print("받은 뒤:  python -m app.ingest.run_attachments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
