"""공시가 지목한 IR URL에서 계획서 PDF를 받아 plan_attachment에 적재.

실행: python -m app.ingest.run_ir_attachments [--dry-run] [--corp 00164779]

동작:
  1. valueup_plan.related_url이 있는 공시를 대상으로(백필: --backfill-urls)
  2. robots.txt 확인(코드 관문 — ir_site.RobotsGate)
  3. **직링크 PDF만** 받는다. 랜딩 페이지는 not_pdf로 보고하고 건너뛴다 —
     페이지에서 PDF를 찾아내는 것은 링크 추적이라 별도 결정 사항이다.
  4. attachments/ 에 저장 → 기존 파싱 층(0017)으로 목표 추출 → 적재

취득 출처가 데이터에 남는다: acquired_by='ir_site', source_url=받은 주소.
수동 취득분(acquired_by='manual')과 구분되므로 나중에 "이 값 어디서 났나"에
파일명·페이지·URL·취득일까지 답할 수 있다.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.analysis.plan_signals import extract_related_url
from app.db import SessionLocal
from app.ingest.attachment import evidence_to_json, parse_pdf, today_iso
from app.ingest.ir_site import IrSiteFetcher
from app.models import Company, PlanAttachment, ValueupPlan

logger = logging.getLogger(__name__)

ATTACH_DIR = Path("attachments")


@dataclass
class IrRunResult:
    fetched: int = 0
    parsed: list[tuple[str, str, int]] = field(default_factory=list)  # (종목, 파일, 축수)
    skipped: list[tuple[str, str]] = field(default_factory=list)      # (종목, 사유)


def backfill_urls(dry_run: bool = False) -> int:
    """raw_text에서 related_url을 뽑아 채운다(네트워크 호출 0)."""
    n = 0
    with SessionLocal() as session:
        with session.begin():
            for plan in session.scalars(select(ValueupPlan)).all():
                url = extract_related_url(plan.raw_text)
                if url and plan.related_url != url:
                    n += 1
                    if not dry_run:
                        plan.related_url = url
            if dry_run:
                session.rollback()
    return n


def run(corp_code: str | None = None, dry_run: bool = False) -> IrRunResult:
    result = IrRunResult()
    fetcher = IrSiteFetcher()

    with SessionLocal() as session:
        stmt = select(ValueupPlan, Company).join(
            Company, Company.corp_code == ValueupPlan.corp_code
        ).where(ValueupPlan.related_url.is_not(None))
        if corp_code:
            stmt = stmt.where(ValueupPlan.corp_code == corp_code)
        rows = session.execute(stmt).all()
        targets = [
            (p.plan_id, p.corp_code, c.corp_name, p.related_url, p.rcept_no,
             p.disclosure_date)
            for p, c in rows
        ]

    for plan_id, code, name, url, rcept, date in targets:
        stem = rcept or f"{code}_{date}"
        dest = ATTACH_DIR / f"{stem}.pdf"
        fr = fetcher.fetch_pdf(url, dest)
        if fr.error:
            result.skipped.append((name or code, f"{fr.error} ({url})"))
            continue
        result.fetched += 1

        parsed = parse_pdf(dest)
        result.parsed.append((name or code, dest.name, parsed.disclosed_axis_count))
        if dry_run:
            continue
        with SessionLocal() as session:
            with session.begin():
                obj = session.scalars(
                    select(PlanAttachment).where(
                        PlanAttachment.plan_id == plan_id,
                        PlanAttachment.filename == dest.name,
                    )
                ).one_or_none()
                if obj is None:
                    obj = PlanAttachment(
                        plan_id=plan_id, corp_code=code, filename=dest.name,
                        acquired_by="ir_site", acquired_at=today_iso(),
                    )
                    session.add(obj)
                obj.acquired_by = "ir_site"
                obj.source_url = url
                obj.sha256 = parsed.sha256
                obj.page_count = parsed.page_count
                obj.parsed_at = today_iso()
                for f, v in parsed.targets.items():
                    setattr(obj, f, v)
                obj.evidence_json = evidence_to_json(parsed.evidence)
                obj.parse_error = parsed.parse_error
                obj.extracted_text = parsed.extracted_text
    return result


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="IR 사이트 계획서 PDF 취득·적재")
    ap.add_argument("--backfill-urls", action="store_true",
                    help="raw_text에서 related_url만 채우고 종료(네트워크 0)")
    ap.add_argument("--corp", help="특정 corp_code만")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.backfill_urls:
        n = backfill_urls(args.dry_run)
        print(f"{'(dry-run) ' if args.dry_run else ''}related_url 채움: {n}건")
        return 0

    r = run(args.corp, args.dry_run)
    print(f"\n받음 {r.fetched}건")
    for name, fn, axes in r.parsed:
        print(f"  ✓ {name[:20]:22s} {fn}  목표 {axes}/4축")
    if r.skipped:
        print(f"\n건너뜀 {len(r.skipped)}건")
        for name, why in r.skipped:
            print(f"  - {name[:20]:22s} {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
