"""기존 valueup_plan 행에 body_signal·attachment_absent 백필 (0018, 0031).

실행: python -m app.analysis.backfill_body_signal [--dry-run]

둘을 한 번에 도는 이유: **같은 원문의 순수 함수**라 판정 시점이 갈리면 안 된다.
다만 서로 **독립적으로** 묻는다 — body_signal은 우선순위 사다리(왜 축을 못 채웠나),
attachment_absent는 선언 문장의 유무(받으러 갈 문서가 있나). 2026-08-04에 후자를
전자의 맨 아래 칸에 넣었다가 8건이 위쪽 신호에 가려 샜다(0031 참조).

재수집 없이 채울 수 있는 이유: valueup_plan은 처음부터 raw_text를 보존해왔다
("원문 보존 + 멱등 upsert"가 1.5의 정확성 계약). 분류는 원문의 순수 함수이므로
DART를 다시 부르지 않는다 — 외부 호출 0.

멱등: 여러 번 돌려도 같은 결과. 파서를 고친 뒤 다시 돌리면 신호가 따라 갱신된다.
"""

from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select

from app.analysis.plan_signals import (
    SIGNAL_LABEL,
    classify_body,
    declares_no_attachment,
)
from app.db import SessionLocal
from app.models import ValueupPlan


def run(dry_run: bool = False) -> tuple[Counter, Counter]:
    """(body_signal 분포, attachment_absent 분포)를 돌려준다.

    두 축을 한 Counter에 섞지 않는다 — 합계가 공시 건수의 두 배가 되어 "몇 건을
    분류했나"를 말할 수 없게 된다. 직교한 사실은 세는 것도 따로 센다.
    """
    counts: Counter = Counter()
    absent_counts: Counter = Counter()
    with SessionLocal() as session:
        with session.begin():
            for plan in session.scalars(select(ValueupPlan)).all():
                targets = {
                    "target_roe": plan.target_roe,
                    "target_payout_ratio": plan.target_payout_ratio,
                    "target_total_return_ratio": plan.target_total_return_ratio,
                    "period_start": plan.period_start,
                    "buyback_planned": plan.buyback_planned,
                }
                signal = classify_body(plan.raw_text, targets)
                counts[signal.kind] += 1
                # 원문이 없으면 선언 여부를 모른다 — False로 굳히지 않는다(NFR2).
                absent = declares_no_attachment(plan.raw_text) if plan.raw_text else None
                absent_counts["미판정(원문 없음)" if absent is None
                              else "첨부 없음 선언" if absent
                              else "선언 없음"] += 1
                if not dry_run:
                    plan.body_signal = signal.kind
                    plan.body_reference_date = signal.referenced_date
                    plan.attachment_absent = absent
            if dry_run:
                session.rollback()
    return counts, absent_counts


def main() -> int:
    ap = argparse.ArgumentParser(
        description="valueup_plan.body_signal·attachment_absent 백필")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    counts, absent_counts = run(args.dry_run)
    total = sum(counts.values())
    print(f"{'(dry-run) ' if args.dry_run else ''}공시 {total}건 분류")
    print("  [본문 신호 — 왜 축을 못 채웠나]")
    for kind, n in counts.most_common():
        print(f"  {n:3d}  {kind:14s} {SIGNAL_LABEL.get(kind, '')}")
    print("  [첨부 부존재 — 받으러 갈 문서가 있나]")
    for label, n in absent_counts.most_common():
        print(f"  {n:3d}  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
