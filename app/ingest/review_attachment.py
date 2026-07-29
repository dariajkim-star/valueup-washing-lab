"""OCR 후보 검토 CLI — 승인·수정·기각 (수동 경로는 입력이 아니라 오버라이드다).

실행:
    python -m app.ingest.review_attachment <파일명> --show
    python -m app.ingest.review_attachment <파일명> --approve --by daria \
        [--set target_payout_ratio=none] [--set target_total_return_ratio=50] [--note ...]
    python -m app.ingest.review_attachment <파일명> --reject "표가 이미지라 신뢰 불가" --by daria

역할을 좁힌 이유(2026-07-29 채택): 사람이 백지에서 값을 타이핑하면 판정 계약이 사람마다
흔들리고 누락이 조용히 유지된다. 여기서는 OCR+파서가 만든 **후보와 근거 페이지**를 놓고
승인/수정/기각만 한다 — 수정(--set)도 후보 위에 얹는 오버라이드이며 review_note에 남는다.

승인의 의미: 이 sha256의 추출 결과가 옳다는 사람의 판정. 파일이 바뀌어 재파싱되면
run_attachments가 검토 기록을 리셋한다(승인은 특정 추출 결과에 대한 것이므로).
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.db import SessionLocal
from app.ingest.attachment import today_iso
from app.models import PlanAttachment

_FIELDS = (
    "target_roe",
    "target_payout_ratio",
    "target_total_return_ratio",
    "target_pbr",
    "period_start",
    "period_end",
    "buyback_planned",
)
_FLOAT_FIELDS = _FIELDS[:4]


def _parse_value(field: str, raw: str):
    """--set 값 해석. 'none'은 값 제거(오탐 기각), buyback은 불리언, 목표는 실수."""
    low = raw.strip().lower()
    if low in ("none", "null", ""):
        return None
    if field == "buyback_planned":
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
        raise SystemExit(f"buyback_planned는 true/false/none만: {raw!r}")
    if field in _FLOAT_FIELDS:
        try:
            return float(raw)
        except ValueError as e:
            raise SystemExit(f"{field}는 숫자 또는 none: {raw!r}") from e
    return raw.strip()  # period_start/end — YYYY-MM-DD 문자열


def _show(obj: PlanAttachment) -> None:
    evidence = json.loads(obj.evidence_json) if obj.evidence_json else {}
    ocr_pages = json.loads(obj.ocr_pages) if obj.ocr_pages else []
    print(f"{obj.filename}  (plan_id={obj.plan_id}, corp={obj.corp_code})")
    print(f"  sha256: {obj.sha256[:16]}…  pages: {obj.page_count}  OCR: p.{ocr_pages}")
    print(f"  needs_review: {obj.needs_review}  parse_error: {obj.parse_error}")
    if obj.reviewed_by:
        print(f"  검토: {obj.reviewed_by} @ {obj.reviewed_at} — {obj.review_note or ''}")
    print("  후보 값:")
    for f in _FIELDS:
        v = getattr(obj, f)
        if v is None:
            continue
        page = evidence.get(f)
        src = f"p.{page}" + (" [OCR]" if page in ocr_pages else " [native]") if page else "?"
        print(f"    {f} = {v}   ({src})")


def main() -> int:
    ap = argparse.ArgumentParser(description="OCR 후보 검토 — 승인·수정·기각")
    ap.add_argument("filename", help="plan_attachment.filename (예: 20260206801698.pdf)")
    ap.add_argument("--show", action="store_true", help="후보·근거만 출력")
    ap.add_argument("--approve", action="store_true", help="승인(--set 오버라이드 적용 후)")
    ap.add_argument("--reject", metavar="REASON", help="기각 — 추출 결과를 신뢰하지 않음")
    ap.add_argument("--set", dest="sets", action="append", default=[],
                    metavar="FIELD=VALUE", help="승인 전 값 수정(none=제거). 반복 가능")
    ap.add_argument("--by", help="검토자 이름(승인·기각에 필수)")
    ap.add_argument("--note", help="검토 메모")
    args = ap.parse_args()

    if args.approve and args.reject:
        raise SystemExit("--approve와 --reject는 함께 쓸 수 없습니다.")
    if (args.approve or args.reject) and not args.by:
        raise SystemExit("승인·기각에는 --by <이름>이 필요합니다.")
    if args.sets and not args.approve:
        raise SystemExit("--set은 --approve와 함께만 씁니다(수정 후 승인).")

    with SessionLocal() as session, session.begin():
        obj = session.scalars(
            select(PlanAttachment).where(PlanAttachment.filename == args.filename)
        ).one_or_none()
        if obj is None:
            raise SystemExit(f"plan_attachment에 없음: {args.filename} (run_attachments 먼저)")

        if args.show or not (args.approve or args.reject):
            _show(obj)
            return 0

        overrides: list[str] = []
        for item in args.sets:
            if "=" not in item:
                raise SystemExit(f"--set 형식은 FIELD=VALUE: {item!r}")
            f, raw = item.split("=", 1)
            f = f.strip()
            if f not in _FIELDS:
                raise SystemExit(f"수정 가능한 필드가 아님: {f} (가능: {', '.join(_FIELDS)})")
            old = getattr(obj, f)
            new = _parse_value(f, raw)
            setattr(obj, f, new)
            overrides.append(f"{f}: {old} → {new}")

        obj.reviewed_by = args.by
        obj.reviewed_at = today_iso()
        note = args.note or ""
        if overrides:
            note = (note + " | " if note else "") + "; ".join(overrides)
        obj.review_note = note[:300] or None

        if args.reject:
            # 기각 = 이 추출 결과를 쓰지 않는다. parse_error로 남겨 채점에서 빠지고,
            # 워크리스트에 다시 나타난다(첨부를 다시 구해야 하는 상태).
            obj.parse_error = f"review_rejected:{args.reject}"[:200]
            obj.needs_review = False
            print(f"기각: {obj.filename} — {args.reject}")
        else:
            obj.needs_review = False
            print(f"승인: {obj.filename}" + (f" (수정 {len(overrides)}건)" if overrides else ""))
            for line in overrides:
                print(f"  · {line}")
        _show(obj)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
