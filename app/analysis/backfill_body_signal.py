"""기존 valueup_plan 행에 body_signal 백필 (0018).

실행: python -m app.analysis.backfill_body_signal [--dry-run]

재수집 없이 채울 수 있는 이유: valueup_plan은 처음부터 raw_text를 보존해왔다
("원문 보존 + 멱등 upsert"가 1.5의 정확성 계약). 분류는 원문의 순수 함수이므로
DART를 다시 부르지 않는다 — 외부 호출 0.

멱등: 여러 번 돌려도 같은 결과. 파서를 고친 뒤 다시 돌리면 신호가 따라 갱신된다.
"""

from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select

from app.analysis.plan_signals import SIGNAL_LABEL, classify_body
from app.db import SessionLocal
from app.models import ValueupPlan


def run(dry_run: bool = False) -> Counter:
    counts: Counter = Counter()
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
                if not dry_run:
                    plan.body_signal = signal.kind
                    plan.body_reference_date = signal.referenced_date
            if dry_run:
                session.rollback()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="valueup_plan.body_signal 백필")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    counts = run(args.dry_run)
    total = sum(counts.values())
    print(f"{'(dry-run) ' if args.dry_run else ''}공시 {total}건 분류")
    for kind, n in counts.most_common():
        print(f"  {n:3d}  {kind:14s} {SIGNAL_LABEL.get(kind, '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
