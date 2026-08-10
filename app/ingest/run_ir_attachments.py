"""공시가 지목한 IR URL에서 계획서 PDF를 받아 plan_attachment에 적재.

실행: python -m app.ingest.run_ir_attachments [--dry-run] [--follow] [--corp 00164779 ...]

동작:
  1. valueup_plan.related_url이 있는 공시를 대상으로(백필: --backfill-urls)
     --corp를 주면 그 종목만 — 백필·취득 양쪽에 걸린다(여러 번 지정 가능).
  2. robots.txt 확인(코드 관문 — ir_site.RobotsGate). robots.txt를 못 받으면
     **닫는 쪽으로** 실패한다(robots_disallowed) — 모르면 안 간다.
  3. 직링크 PDF를 받는다. 랜딩 페이지면 --follow로 그 안의 계획서 PDF까지
     **1홉만** 추적한다(페이지의 페이지로 넘어가지 않으므로 크롤링이 아니다).
     후보에 계획서 시사어가 없으면 ambiguous로 남기고 **고르지 않는다** —
     자료실에서 아무 PDF나 집어 계획서로 적재하는 것은 빈손보다 나쁘다(NFR2).
  4. attachments/ 에 저장 → 기존 파싱 층(0017)으로 목표 추출 → 적재

⚠️ 이 경로가 만능이 아니다 (2026-08-07 실측 · 첨부 대상 8개사 11 URL → **취득 0건**):
    http_403 2 · no_pdf_links 5(JS 렌더링 SPA) · robots_disallowed 2 · ambiguous 2.
    ambiguous 2건은 후보가 각각 Annual Report·Company Profile이라 **거부가 정답**이었다.
    즉 취득 실패의 대부분은 버그가 아니라 경계다 — 이 경우 사람이 브라우저로 받아
    attachments/에 두면 run_attachments(수동 경로)가 이어받는다. 두 경로는 대체재가
    아니라 보완재이며, acquired_by('ir_site'/'manual')로 출처가 갈려 남는다.

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
    # 1홉으로 찾아낸 것 (종목, 랜딩페이지, 실제 PDF) — 출처 체인을 사람이 검증할 수 있게
    followed: list[tuple[str, str, str]] = field(default_factory=list)


def backfill_urls(dry_run: bool = False, corp_codes: list[str] | None = None) -> int:
    """raw_text에서 related_url을 뽑아 채운다(네트워크 호출 0).

    corp_codes를 주면 그 종목만 채운다. 전건 백필은 212건을 한꺼번에 움직이므로,
    취득 대상이 정해진 작업에서는 범위를 좁혀 무엇이 왜 바뀌었는지 추적 가능하게 둔다.
    """
    n = 0
    with SessionLocal() as session:
        with session.begin():
            stmt = select(ValueupPlan)
            if corp_codes:
                stmt = stmt.where(ValueupPlan.corp_code.in_(corp_codes))
            for plan in session.scalars(stmt).all():
                url = extract_related_url(plan.raw_text)
                if url and plan.related_url != url:
                    n += 1
                    if not dry_run:
                        plan.related_url = url
            if dry_run:
                session.rollback()
    return n


def run(corp_code: str | list[str] | None = None, dry_run: bool = False,
        follow: bool = False) -> IrRunResult:
    result = IrRunResult()
    fetcher = IrSiteFetcher()

    with SessionLocal() as session:
        stmt = select(ValueupPlan, Company).join(
            Company, Company.corp_code == ValueupPlan.corp_code
        ).where(ValueupPlan.related_url.is_not(None))
        if corp_code:
            codes = [corp_code] if isinstance(corp_code, str) else list(corp_code)
            stmt = stmt.where(ValueupPlan.corp_code.in_(codes))
        rows = session.execute(stmt).all()
        targets = [
            (p.plan_id, p.corp_code, c.corp_name, p.related_url, p.rcept_no,
             p.disclosure_date)
            for p, c in rows
        ]

    for plan_id, code, name, url, rcept, date in targets:
        stem = rcept or f"{code}_{date}"
        dest = ATTACH_DIR / f"{stem}.pdf"
        pdf_url = url
        fr = fetcher.fetch_pdf(pdf_url, dest)

        # 1홉 추적: 공시가 준 주소가 랜딩 페이지면 그 안의 계획서 PDF 링크까지만 따라간다.
        # 실측상 이 경우가 다수다(49건 중 43건이 not_pdf). 페이지의 페이지로는 넘어가지
        # 않으므로 크롤링이 아니다.
        if follow and fr.error and fr.error.startswith("not_pdf"):
            found, ferr, cands = fetcher.resolve_plan_pdf(url)
            if found:
                pdf_url = found
                fr = fetcher.fetch_pdf(pdf_url, dest)
                if not fr.error:
                    result.followed.append((name or code, url, pdf_url))
            else:
                result.skipped.append((name or code, f"{ferr} ({url})"))
                continue

        if fr.error:
            result.skipped.append((name or code, f"{fr.error} ({pdf_url})"))
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
                # 실제로 받은 PDF의 주소(1홉으로 찾았다면 그 결과). 랜딩 페이지는
                # valueup_plan.related_url에 이미 있어 출처 체인이 복원된다.
                obj.source_url = pdf_url
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
    ap.add_argument("--corp", action="append",
                    help="특정 corp_code만 (여러 번 지정 가능)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--follow", action="store_true",
                    help="랜딩 페이지면 그 안의 계획서 PDF 링크까지 1홉 추적")
    args = ap.parse_args()

    if args.backfill_urls:
        n = backfill_urls(args.dry_run, args.corp)
        print(f"{'(dry-run) ' if args.dry_run else ''}related_url 채움: {n}건")
        return 0

    r = run(args.corp, args.dry_run, follow=args.follow)
    print(f"\n받음 {r.fetched}건")
    for name, fn, axes in r.parsed:
        print(f"  ✓ {name[:20]:22s} {fn}  목표 {axes}/4축")
    if r.followed:
        print(f"\n1홉 추적으로 찾음 {len(r.followed)}건 — 출처 체인을 확인하세요")
        for name, page, pdf in r.followed:
            print(f"  {name[:20]:22s}")
            print(f"     페이지: {page}")
            print(f"     PDF   : {pdf}")
    if r.skipped:
        print(f"\n건너뜀 {len(r.skipped)}건")
        for name, why in r.skipped:
            print(f"  - {name[:20]:22s} {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
