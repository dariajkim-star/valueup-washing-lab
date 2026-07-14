"""Tableau Public용 CSV export 배치 (Story 3.5).

Tableau Public은 라이브 DB 연결을 지원하지 않으므로(epics AC "PostgreSQL 연결"의
의도적 일탈 — 스토리 문서 참조) DB 뷰/테이블에서 뷰별 tidy CSV를 뽑아 파일 소스로
물린다. "각 뷰가 API/DB 뷰를 소스로 갱신된다"는 이 스크립트 재실행 → CSV 갱신 →
Tableau 새로고침으로 충족.

레이어 규정: ingest와 동급의 배치 레이어(read-only, routers 미의존 — AD-2 단방향).
SQL은 전부 repositories/export.py 경유.

계약:
- 단일 as_of: 모든 스코어 계열 CSV는 같은 기준일로 수렴(3.4 리뷰 High 교훈).
- null 정직성: null은 빈 셀. 0 치환·기본값 채움 금지(1.8부터의 프로젝트 계약).
- 실패는 명시적: 스코어가 한 건도 없으면 빈 CSV를 쓰지 않고 에러로 중단
  (에러를 빈 데이터로 세탁하지 않는다 — 2.6/3.4 리뷰 계보).

실행: python -m app.export.tableau [--out exports/tableau]
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.repositories import export as export_repo
from app.repositories.screening import latest_as_of

logger = logging.getLogger(__name__)

DEFAULT_OUT_DIR = Path("exports/tableau")


class NoScoreDataError(RuntimeError):
    """스코어 테이블이 비어 as_of를 정할 수 없음 — 빈 CSV 세탁 대신 명시적 중단."""


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> int:
    """tidy CSV 기록. None은 csv 모듈이 빈 셀로 쓴다(null≠0 계약).

    bool은 Tableau가 문자열 "True"/"False"로 읽으므로 그대로 두되 소문자 통일
    (washing_flag 필터 계산식이 대소문자에 흔들리지 않게).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # BOM: Tableau/Excel 한글 호환
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="raise")
        writer.writeheader()
        for row in rows:
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
        "corp_code", "corp_name", "sector", "as_of", "year", "quarter",
        "dividend_total", "payout_ratio", "buyback_amount",
        "buyback_retired_amount", "buyback_status",
    ],
    "macro_layer": ["indicator", "date", "value", "frequency"],
}


def export_all(session: Session, out_dir: Path) -> dict[str, int]:
    """5개 CSV 전부 기록, {뷰: 행수} 반환. as_of는 단일값으로 수렴."""
    as_of = latest_as_of(session)
    if as_of is None:
        raise NoScoreDataError(
            "valueup_score/mna_score가 비어 있어 기준일(as_of)을 정할 수 없습니다 — "
            "엔진 실행 후 다시 export하세요."
        )
    logger.info("export as_of=%s → %s", as_of, out_dir)

    rows_by_view: dict[str, list[dict[str, Any]]] = {
        "valueup_scores": export_repo.valueup_scores_rows(session, as_of),
        "sector_valuation_map": export_repo.sector_valuation_rows(session, as_of),
        "roe_pbr_scatter": export_repo.roe_pbr_rows(session, as_of),
        "dividend_buyback": export_repo.dividend_buyback_rows(session, as_of),
        "macro_layer": export_repo.macro_rows(session),
    }
    counts: dict[str, int] = {}
    for view, rows in rows_by_view.items():
        counts[view] = _write_csv(out_dir / f"{view}.csv", rows, VIEW_COLUMNS[view])
        logger.info("  %s.csv: %d rows", view, counts[view])
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
