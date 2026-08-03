"""기존 valueup_plan 행의 목표 필드 재파싱 백필 (P1-5, 2026-08-03).

실행: python -m app.analysis.backfill_targets [--dry-run]

재수집 없이 채울 수 있는 이유는 `backfill_body_signal`과 같다 — valueup_plan은 처음부터
raw_text를 보존해왔고(1.5 정확성 계약), `parse_targets`는 원문의 순수 함수다. DART 호출 0.

**기존 non-null은 건드리지 않는다.** 파서 확장(범위·수식어·역순)은 전부 "못 찾았을 때만"
도는 폴백이므로 재파싱이 값을 바꿀 일이 없지만, 그 사실을 여기서도 강제한다 — 백필이
조용히 값을 갈아치우면 어제의 채점과 오늘의 채점이 다른 이유를 아무도 설명할 수 없다.
바꿔야 할 값이 나오면 **적용하지 않고 보고**한다(--dry-run과 무관하게).

멱등: 여러 번 돌려도 같은 결과.
"""

from __future__ import annotations

import argparse
from collections import Counter

from sqlalchemy import select

from app.db import SessionLocal
from app.ingest.dart_valueup import parse_targets
from app.models import ValueupPlan

# 재파싱으로 채울 필드. period_*·buyback_planned는 별도 규칙(P1-8)이 소유하므로 건드리지 않는다.
_FIELDS = (
    "target_roe",
    "target_payout_ratio",
    "target_total_return_ratio",
    "target_pbr",
)


def run(dry_run: bool = False) -> tuple[Counter, list[str]]:
    """(필드별 신규 회수 건수, 기존값이 달라진 경우의 보고 목록)."""
    gained: Counter = Counter()
    conflicts: list[str] = []
    with SessionLocal() as session:
        with session.begin():
            for plan in session.scalars(select(ValueupPlan)).all():
                parsed = parse_targets(plan.raw_text, plan.disclosure_date)
                for field in _FIELDS:
                    old, new = getattr(plan, field), parsed[field]
                    if old is None and new is not None:
                        gained[field] += 1
                        if not dry_run:
                            setattr(plan, field, new)
                    elif old is not None and new != old:
                        # 적용하지 않는다 — 기존 값이 어떤 규칙에서 나왔는지 여기서 알 수 없다.
                        conflicts.append(
                            f"{plan.corp_code} {plan.disclosure_date} {field}: {old} → {new}"
                        )
                if not dry_run and parsed["target_ranges"] and not plan.target_ranges:
                    plan.target_ranges = parsed["target_ranges"]
            if dry_run:
                session.rollback()
    return gained, conflicts


def main() -> int:
    ap = argparse.ArgumentParser(description="valueup_plan 목표 필드 재파싱 백필")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    gained, conflicts = run(args.dry_run)
    prefix = "(dry-run) " if args.dry_run else ""
    print(f"{prefix}신규 회수 {sum(gained.values())}건")
    for field, n in gained.most_common():
        print(f"  +{n:3d}  {field}")
    print(f"{prefix}기존값 충돌(미적용) {len(conflicts)}건")
    for c in conflicts[:20]:
        print(f"  ! {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
