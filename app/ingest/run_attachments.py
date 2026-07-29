"""attachments/ 폴더 → plan_attachment 적재 (수동 취득분 파싱 배치).

실행: python -m app.ingest.run_attachments [--dir attachments] [--dry-run]

취득은 사람이 한다(DART robots.txt Disallow — app/ingest/attachment.py 모듈 문서 참조).
이 배치는 받아둔 파일을 **어느 공시의 첨부인지 묶고**, 파싱하고, 출처와 함께 저장한다.

멱등성: (plan_id, filename) 자연키 + sha256 비교. 같은 파일이면 재파싱하지 않고 건너뛴다
(--force로 강제). 파일이 바뀌면 sha256이 달라지므로 자동으로 다시 읽는다.

매칭 실패를 조용히 넘기지 않는다: 이름 규약에 안 맞거나 해당 공시가 DB에 없으면
skipped에 사유와 함께 담아 보고한다 — 사용자가 파일 이름을 고칠 수 있어야 하므로.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.ingest.attachment import (
    AttachmentRef,
    ParsedAttachment,
    evidence_to_json,
    parse_pdf,
    scan_directory,
    today_iso,
)
from app.models import PlanAttachment, ValueupPlan

logger = logging.getLogger(__name__)

DEFAULT_DIR = Path("attachments")


@dataclass
class AttachmentRunResult:
    parsed: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (파일명, 사유)
    unreadable: list[tuple[str, str]] = field(default_factory=list)  # (파일명, parse_error)
    matched: list[tuple[str, str, int]] = field(default_factory=list)  # (파일명, 종목, 공시축수)
    # OCR 유래 값이 있어 사람 승인이 필요한 건 — (파일명, OCR 페이지, 추출 목표)
    needs_review: list[tuple[str, list[int], dict]] = field(default_factory=list)


def _resolve_plan(session, ref: AttachmentRef) -> ValueupPlan | None:
    """파일 이름 → valueup_plan 행. 접수번호 우선, 없으면 (corp_code, 공시일)."""
    if ref.rcept_no:
        return session.scalars(
            select(ValueupPlan).where(ValueupPlan.rcept_no == ref.rcept_no)
        ).first()
    if ref.corp_code and ref.disclosure_date:
        return session.scalars(
            select(ValueupPlan).where(
                ValueupPlan.corp_code == ref.corp_code,
                ValueupPlan.disclosure_date == ref.disclosure_date,
            )
        ).first()
    return None


def _upsert(session, plan: ValueupPlan, parsed: ParsedAttachment) -> PlanAttachment:
    obj = session.scalars(
        select(PlanAttachment).where(
            PlanAttachment.plan_id == plan.plan_id,
            PlanAttachment.filename == parsed.path.name,
        )
    ).one_or_none()
    if obj is None:
        obj = PlanAttachment(
            plan_id=plan.plan_id,
            corp_code=plan.corp_code,
            filename=parsed.path.name,
            acquired_by="manual",
            acquired_at=today_iso(),
        )
        session.add(obj)
    obj.sha256 = parsed.sha256
    obj.page_count = parsed.page_count
    obj.parsed_at = today_iso()
    for f, v in parsed.targets.items():
        setattr(obj, f, v)
    obj.evidence_json = evidence_to_json(parsed.evidence)
    obj.parse_error = parsed.parse_error
    obj.extracted_text = parsed.extracted_text
    # OCR 층(0020). 내용이 바뀌어 재파싱된 경우 이전 승인은 무효다 — 승인은 특정
    # sha256의 추출 결과에 대한 판정이었으므로 검토 기록을 리셋한다.
    import json as _json

    obj.ocr_pages = _json.dumps(parsed.ocr_pages) if parsed.ocr_pages else None
    obj.needs_review = parsed.needs_review
    obj.reviewed_by = None
    obj.reviewed_at = None
    obj.review_note = None
    return obj


def run(directory: Path = DEFAULT_DIR, *, force: bool = False,
        dry_run: bool = False) -> AttachmentRunResult:
    result = AttachmentRunResult()
    refs = scan_directory(directory)
    if not refs:
        logger.info("첨부 없음: %s", directory)
        return result

    for ref in refs:
        name = ref.path.name
        with SessionLocal() as session:
            with session.begin():
                plan = _resolve_plan(session, ref)
                if plan is None:
                    reason = (
                        "이름 규약 불일치({rcept_no}.pdf 또는 {corp_code}_{YYYY-MM-DD}.pdf)"
                        if not (ref.rcept_no or ref.corp_code)
                        else "해당 공시가 DB에 없음(재수집 필요)"
                    )
                    result.skipped.append((name, reason))
                    continue

                existing = session.scalars(
                    select(PlanAttachment).where(
                        PlanAttachment.plan_id == plan.plan_id,
                        PlanAttachment.filename == name,
                    )
                ).one_or_none()

                parsed = parse_pdf(ref.path)
                if existing and existing.sha256 == parsed.sha256 and not force:
                    result.skipped.append((name, "이미 파싱됨(내용 동일)"))
                    continue

                if parsed.parse_error:
                    result.unreadable.append((name, parsed.parse_error))
                if parsed.needs_review:
                    result.needs_review.append((
                        name, parsed.ocr_pages,
                        {k: v for k, v in parsed.targets.items() if v is not None},
                    ))
                if not dry_run:
                    _upsert(session, plan, parsed)
                result.parsed += 1
                result.matched.append(
                    (name, plan.corp_code, parsed.disclosed_axis_count)
                )
    return result


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="attachments/ → plan_attachment 적재")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--force", action="store_true", help="내용이 같아도 재파싱")
    ap.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 결과만 출력")
    args = ap.parse_args()

    r = run(args.dir, force=args.force, dry_run=args.dry_run)
    print(f"\n파싱 {r.parsed}건")
    for name, corp, axes in r.matched:
        print(f"  ✓ {name} → {corp} (목표 {axes}/4축)")
    if r.needs_review:
        print(f"\n검토 필요 {len(r.needs_review)}건 — OCR 유래 값은 승인 전까지 채점에 안 들어감")
        for name, pages, cand in r.needs_review:
            print(f"  ? {name} (OCR p.{','.join(map(str, pages))}): {cand}")
        print("  검토:  python -m app.ingest.review_attachment <파일명> --show")
    if r.unreadable:
        print(f"\n못 읽음 {len(r.unreadable)}건 — '미공시'가 아니라 '읽지 못함'으로 기록됨")
        for name, err in r.unreadable:
            print(f"  ! {name}: {err}")
    if r.skipped:
        print(f"\n건너뜀 {len(r.skipped)}건")
        for name, why in r.skipped:
            print(f"  - {name}: {why}")
    # 못 읽은 파일이 있어도 종료 코드는 0 — 실패가 아니라 정직하게 기록된 상태다.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
