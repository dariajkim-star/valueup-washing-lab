"""무엇을 받아야 하는가 — 첨부가 필요한 공시 목록 출력.

실행: python -m app.ingest.attachment_worklist

취득이 수동이므로(DART robots.txt — attachment.py 모듈 문서 참조), 사람이 **무엇을·어디서·
어떤 이름으로** 받아야 하는지 정확히 알아야 한다. 그 목록을 코드가 만든다 — 사람이
DB를 뒤져 대상을 고르게 하면 그게 진짜 수작업이 된다.

대상 우선순위:
  1. 순위 불가(4축 전무) — 첨부 없이는 살릴 방법이 없는 종목. 여기가 첨부의 본래 목적.
  2. 부분 공시(1~3축) — 첨부에 나머지가 있을 수 있다.
이미 첨부를 파싱한 공시는 제외한다.

**받을 수 없는 것은 부르지 않는다(2026-08-04)**: `exempt_short_form` — 회사가 본문에
"첨부 없이 주요 내용을 기재하였습니다"라고 명시한 약식 공시는 제외한다. 이전에는
목록이 129건이었는데 그중 101개사가 이 부류였다. **존재하지 않는 문서를 찾아오라고
사람을 보내는 목록**은 작업 목록이 아니라 오답이다. 분류 근거는 `plan_signals.py`.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.analysis.plan_selection import (
    EXEMPT_SHORT_FORM,
    OTHER_METRIC,
    choose_plan,
    disclosed_axis_count,
)
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
                "rcept_no": p.rcept_no, "related_url": p.related_url,
                "target_roe": p.target_roe,
                "target_payout_ratio": p.target_payout_ratio,
                "target_total_return_ratio": p.target_total_return_ratio,
                "period_start": p.period_start, "buyback_planned": p.buyback_planned,
                # 재공시를 건너뛰어 **실계획**을 대상으로 삼는다(0018). 이게 없으면
                # 우리금융에 03-23(고배당기업 표시용 재공시)의 첨부를 요구하게 된다.
                "body_signal": p.body_signal,
                "body_reference_date": p.body_reference_date,
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
        # [2026-08-04] 회사가 **첨부가 없다고 본문에 명시**한 약식 공시는 부르지 않는다.
        # 이전에는 이 목록이 129건이었고 그 대부분(101개사)이 이 부류였다 — 존재하지
        # 않는 문서를 찾아오라고 사람을 보내고 있었다. 목록은 "받을 수 있는 것"만 담는다.
        if chosen.get("body_signal") == EXEMPT_SHORT_FORM:
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
            "body_signal": chosen.get("body_signal"),
            "related_url": chosen.get("related_url"),
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
        if r["body_signal"] == OTHER_METRIC:
            # 받아도 우리 축이 안 나올 수 있다는 신호 — 헛수고를 미리 알린다.
            print("   주의:  본문에 목표가 있으나 **우리 4축 밖**의 지표다"
                  "(예: 매출·EBITDA·CapEx). 첨부에도 ROE·환원율이 없을 수 있다.")
        # ⚠ DART에는 첨부 실물이 없다(2026-07-29 실증 2회: robots.txt Disallow + 사람이
        # 직접 받아도 본문 통지문 HTML뿐). 실물은 회사 IR 페이지에 있으므로 그쪽을
        # 1순위로 안내한다. DART 링크는 원문 대조용으로만 남긴다.
        if r["related_url"]:
            print(f"   받기:  {r['related_url']}   ← 회사 IR(계획서 실물)")
        else:
            print("   받기:  공시에 '관련 웹페이지'가 없다 — 회사 IR을 직접 찾아야 함")
        if r["url"]:
            print(f"   원문:  {r['url']}   (DART 공시 본문 — 첨부 실물은 없음)")
        print(f"   저장:  attachments/{r['save_as']}\n")
    print("받은 뒤:  python -m app.ingest.run_attachments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
