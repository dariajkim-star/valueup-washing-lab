"""Tableau Public용 CSV export 배치 (Story 3.5).

Tableau Public은 라이브 DB 연결을 지원하지 않으므로(epics AC "PostgreSQL 연결"의
의도적 일탈 — 스토리 문서 참조) DB 뷰/테이블에서 뷰별 tidy CSV를 뽑아 파일 소스로
물린다. "각 뷰가 API/DB 뷰를 소스로 갱신된다"는 이 스크립트 재실행 → CSV 갱신 →
Tableau 새로고침으로 충족.

레이어 규정: ingest와 동급의 배치 레이어(read-only, routers 미의존 — AD-2 단방향).
SQL은 전부 repositories/export.py 경유.

계약(GPT 리뷰 반영으로 강화):
- 단일 as_of는 **두 엔진 교집합 최신**: 한 엔진만 실행된 날짜를 고르면 다른 쪽
  CSV가 통째로 0행이 되며 조용히 성공한다 — 교집합이 없으면 명시적 에러.
- 원자적 스냅숏: staging 디렉터리에 5개 전부 + manifest.json을 쓴 뒤 한 번에
  교체 — 부분 실패 시 기존 출력이 그대로 남고 세대가 섞이지 않는다.
- 스키마 강제: row 키가 뷰 스키마와 정확히 일치하지 않으면 ExportSchemaError —
  누락 키를 빈 셀(정상 null)로 세탁하지 않는다.
- null 정직성: null은 빈 셀. 0 치환·기본값 채움 금지(1.8부터의 프로젝트 계약).

실행: python -m app.export.tableau [--out exports/tableau]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.repositories import export as export_repo

logger = logging.getLogger(__name__)

DEFAULT_OUT_DIR = Path("exports/tableau")
MANIFEST_NAME = "manifest.json"


class NoScoreDataError(RuntimeError):
    """두 엔진 공통 as_of가 없음 — 빈/반쪽 CSV 세탁 대신 명시적 중단."""


class ExportSchemaError(RuntimeError):
    """repository row 키가 뷰 스키마와 불일치 — 프로그래밍 오류를 null로 세탁 금지."""


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> int:
    """tidy CSV 기록. None은 csv 모듈이 빈 셀로 쓴다(null≠0 계약).

    row 키 집합이 스키마와 다르면(누락 포함) ExportSchemaError — DictWriter의
    extrasaction="raise"는 추가 키만 잡고 누락 키는 빈 셀로 통과시키므로
    직접 검사한다(GPT 리뷰 Med). bool은 소문자 통일(Tableau 계산식 안정성).
    """
    expected = set(columns)
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM: Tableau/Excel 한글 호환
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for i, row in enumerate(rows):
            actual = set(row)
            if actual != expected:
                raise ExportSchemaError(
                    f"{path.name} row={i}: missing={sorted(expected - actual)}, "
                    f"extra={sorted(actual - expected)}"
                )
            writer.writerow({
                k: (str(v).lower() if isinstance(v, bool) else v)
                for k, v in row.items()
            })
    return len(rows)


VIEW_COLUMNS: dict[str, list[str]] = {
    "valueup_scores": [
        "corp_code", "corp_name", "market", "sector", "as_of",
        "execution_score", "achievement_rate", "progress_rate",
        "washing_flag", "buyback_status",
    ],
    "sector_valuation_map": [
        "corp_code", "corp_name", "market", "sector", "as_of",
        "metrics_year", "metrics_quarter", "pbr", "per", "ev_ebitda",
        "mna_target_score", "valuation_score", "population_basis",
    ],
    "roe_pbr_scatter": [
        "corp_code", "corp_name", "market", "sector", "as_of",
        "metrics_year", "metrics_quarter", "roe", "pbr",
        "execution_score", "washing_flag",
    ],
    "dividend_buyback": [
        "corp_code", "corp_name", "market", "sector", "as_of", "year", "quarter",
        "dividend_total", "payout_ratio", "buyback_amount",
        "buyback_retired_amount", "period_buyback_status",
    ],
    "macro_layer": ["indicator", "date", "value", "frequency"],
}


def export_all(session: Session, out_dir: Path) -> dict[str, int]:
    """5개 CSV + manifest.json을 staging에 쓴 뒤 out_dir로 원자적 교체.

    실패 시 out_dir의 기존 스냅숏은 그대로 남는다(세대 혼합·부분 갱신 금지 —
    GPT 리뷰 High). 반환: {뷰: 행수}.
    """
    as_of = export_repo.latest_common_as_of(session)
    if as_of is None:
        raise NoScoreDataError(
            "valueup_score와 mna_score가 공유하는 as_of가 없습니다 — 두 엔진을 "
            "같은 기준일로 실행한 뒤 export하세요(한쪽만 최신이면 그 날짜의 다른 쪽 "
            "CSV가 0행이 되므로 거부)."
        )
    logger.info("export as_of=%s → %s", as_of, out_dir)

    rows_by_view: dict[str, list[dict[str, Any]]] = {
        "valueup_scores": export_repo.valueup_scores_rows(session, as_of),
        "sector_valuation_map": export_repo.sector_valuation_rows(session, as_of),
        "roe_pbr_scatter": export_repo.roe_pbr_rows(session, as_of),
        "dividend_buyback": export_repo.dividend_buyback_rows(session, as_of),
        "macro_layer": export_repo.macro_rows(session),
    }

    staging = out_dir.parent / f".{out_dir.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        counts: dict[str, int] = {}
        for view, rows in rows_by_view.items():
            counts[view] = _write_csv(staging / f"{view}.csv", rows, VIEW_COLUMNS[view])
            logger.info("  %s.csv: %d rows", view, counts[view])
        manifest = {
            "as_of": as_of,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "views": counts,
        }
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # 전부 성공했을 때만 교체 — Windows에서 rename은 대상 존재 시 실패하므로
        # rmtree 후 rename(그 사이 크래시면 스냅숏이 사라질 수 있으나, 섞인
        # 세대가 남는 것보다 "없음"이 안전 — manifest 부재로 즉시 식별됨).
        if out_dir.exists():
            shutil.rmtree(out_dir)
        staging.rename(out_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tableau Public용 CSV export")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR,
                        help=f"출력 디렉터리 (기본 {DEFAULT_OUT_DIR})")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    session = SessionLocal()
    try:
        counts = export_all(session, args.out)
    finally:
        session.close()
    total = sum(counts.values())
    logger.info("완료: %d개 뷰, 총 %d행", len(counts), total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
