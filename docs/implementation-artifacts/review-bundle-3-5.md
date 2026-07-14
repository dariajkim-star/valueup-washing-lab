# Review Bundle — Story 3.5 (Tableau CSV export)

리뷰 대상: 밸류업 워싱 스크리너의 Tableau Public 연계 스토리. 에픽 AC는 "Tableau를 PostgreSQL에 연결"이지만 실스택은 SQLite이고 Tableau Public은 라이브 DB 연결을 지원하지 않아, **CSV export 레이어로 의도적 일탈**했다(스토리 문서에 결정 근거). 리뷰 관점: 이 일탈의 타당성, export 계약(단일 as_of·null 정직성·명시적 실패), look-ahead 규칙의 API 패리티, CSV 스키마·스펙 문서의 Tableau 실사용 적합성.

## 이미 알려진 것 (재지적 불필요)

- look-ahead는 "부분 차단"(같은 해 quarter=4만 배제) — 완전 해결은 available_at 수집 별도 스토리(deferred-work, 3-3 3라운드에서 기각 확정된 사안).
- sector는 DART induty 코드 원문(API도 동일) — 표시 매핑은 스코프 밖.
- dividend_total은 best-effort 수집(구조적 null 다수).
- 감가상각비 미수집 → ev_ebitda는 EBIT 근사(1.7 deferred).
- Tableau 워크북 조립·게시는 GUI 수작업 — 코드 산출물 범위 밖.
- 2단계 IN·Python dedupe 확장성은 유니버스 확대 선행조건으로 defer(3-3).

## 검증 완료 사항

- pytest 237 passed(기존 231 + 신규 6, 회귀 0).
- 실데이터(valueup.db, KOSPI 33종목) export: as_of=2026-07-13, 5개 CSV(26/33/31/66/3369행).
- API 패리티: /stats/summary(판정모수 19·워싱 0·ratio 0.0)·/stats/macro(최신값 4종) 전부 CSV와 일치.

## `app/repositories/export.py`

```python
"""Tableau export 조회 저장소 (AD-2: SQL은 여기서만).

모든 함수는 **읽기 전용** SELECT(AD-4/AD-10의 writer 제약과 직교). 파생지표는
`valuation_metrics` VIEW를 SELECT할 뿐 재계산하지 않는다(AD-1). 스코어 계열은
호출자가 넘긴 **단일 as_of**의 행만 조회 — 뷰별 CSV가 서로 다른 기준일로 뽑혀
대시보드에서 시점이 섞이는 것(3.4 리뷰 High와 같은 함정)을 저장소 계약으로 차단.

look-ahead 최신 지표는 screening/stats와 동일한 "부분 차단" 규칙
(`year < yr OR (year = yr AND quarter < 4)`) — 규칙이 엔드포인트 간 갈라지면
CSV와 API 수치 패리티가 깨진다(이 스토리 AC의 검증 축).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Company, MacroIndicator, MnaScore, ValueupScore


def _latest_metrics_map(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """corp별 look-ahead 부분 차단 최신 지표 행(전 컬럼). screening._latest_metrics_map과
    같은 규칙이지만 산점도·업종맵이 쓰는 컬럼이 더 넓어(year·quarter 포함) 독립 작성
    (시그니처가 소비자마다 다른 look-ahead 패턴 5번째 사용처 — 공통화는 deferred-work 기존 항목).
    """
    as_of_year = int(as_of[:4])
    rows = session.execute(
        text(
            "SELECT corp_code, year, quarter, roe, pbr, per, ev_ebitda, debt_ratio, "
            "payout_ratio FROM valuation_metrics "
            "WHERE year < :yr OR (year = :yr AND quarter < 4) "
            "ORDER BY corp_code, year DESC, quarter DESC"
        ),
        {"yr": as_of_year},
    ).mappings().all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row["corp_code"] not in latest:  # 정렬상 corp별 첫 행 = 최신
            latest[row["corp_code"]] = dict(row)
    return latest


def valueup_scores_rows(session: Session, as_of: str) -> list[dict[str, Any]]:
    """뷰 1(밸류업 점수): valueup_score(as_of 고정) ⋈ company."""
    rows = session.execute(
        select(
            Company.corp_code, Company.corp_name, Company.market, Company.sector,
            ValueupScore.as_of, ValueupScore.execution_score,
            ValueupScore.achievement_rate, ValueupScore.progress_rate,
            ValueupScore.washing_flag, ValueupScore.buyback_status,
        )
        .join(ValueupScore, ValueupScore.corp_code == Company.corp_code)
        .where(ValueupScore.as_of == as_of)
        .order_by(Company.corp_code)
    ).mappings().all()
    return [dict(r) for r in rows]


def sector_valuation_rows(session: Session, as_of: str) -> list[dict[str, Any]]:
    """뷰 2(업종별 저평가 맵): 최신 지표 ⋈ company ⋈ mna_score(as_of 고정).

    mna_score가 없는 종목(미지원 업종 등)도 지표가 있으면 행을 남기고 스코어는
    빈 값 — null을 조인으로 감추지 않는다(스크리닝 저장소와 같은 정직 노출).
    """
    metrics = _latest_metrics_map(session, as_of)
    companies = session.execute(
        select(Company.corp_code, Company.corp_name, Company.market, Company.sector)
        .order_by(Company.corp_code)
    ).mappings().all()
    mna = {
        r["corp_code"]: r
        for r in session.execute(
            select(
                MnaScore.corp_code, MnaScore.mna_target_score,
                MnaScore.valuation_score, MnaScore.population_basis,
            ).where(MnaScore.as_of == as_of)
        ).mappings()
    }
    out: list[dict[str, Any]] = []
    for c in companies:
        m = metrics.get(c["corp_code"])
        if m is None:  # 지표 자체가 없는 종목은 맵에 놓을 수치가 없음
            continue
        s = mna.get(c["corp_code"], {})
        out.append({
            "corp_code": c["corp_code"], "corp_name": c["corp_name"],
            "market": c["market"], "sector": c["sector"], "as_of": as_of,
            "metrics_year": m["year"], "metrics_quarter": m["quarter"],
            "pbr": m["pbr"], "per": m["per"], "ev_ebitda": m["ev_ebitda"],
            "mna_target_score": s.get("mna_target_score"),
            "valuation_score": s.get("valuation_score"),
            "population_basis": s.get("population_basis"),
        })
    return out


def roe_pbr_rows(session: Session, as_of: str) -> list[dict[str, Any]]:
    """뷰 3(ROE-PBR 산점도): 최신 지표 ⋈ company ⋈ valueup_score(as_of 고정, 색·모양 인코딩용)."""
    metrics = _latest_metrics_map(session, as_of)
    companies = session.execute(
        select(Company.corp_code, Company.corp_name, Company.market, Company.sector)
        .order_by(Company.corp_code)
    ).mappings().all()
    vs = {
        r["corp_code"]: r
        for r in session.execute(
            select(
                ValueupScore.corp_code, ValueupScore.execution_score,
                ValueupScore.washing_flag,
            ).where(ValueupScore.as_of == as_of)
        ).mappings()
    }
    out: list[dict[str, Any]] = []
    for c in companies:
        m = metrics.get(c["corp_code"])
        if m is None or (m["roe"] is None and m["pbr"] is None):
            continue  # 산점도에 놓을 좌표가 전혀 없는 행은 제외(한 축만 null이면 유지 — Tableau가 축별 제외)
        s = vs.get(c["corp_code"], {})
        out.append({
            "corp_code": c["corp_code"], "corp_name": c["corp_name"],
            "market": c["market"], "sector": c["sector"], "as_of": as_of,
            "metrics_year": m["year"], "metrics_quarter": m["quarter"],
            "roe": m["roe"], "pbr": m["pbr"],
            "execution_score": s.get("execution_score"),
            "washing_flag": s.get("washing_flag"),
        })
    return out


def dividend_buyback_rows(session: Session, as_of: str) -> list[dict[str, Any]]:
    """뷰 4(배당/자사주): financials 연도별 환원 원천 + valuation_metrics.payout_ratio
    ⋈ valueup_score(as_of 고정)의 buyback_status. 시계열 축(year)을 가진 유일한 뷰 —
    look-ahead 규칙은 지표 뷰와 동일하게 적용(같은 해 사업보고서 배제).
    """
    as_of_year = int(as_of[:4])
    fin = session.execute(
        text(
            "SELECT f.corp_code, f.year, f.quarter, f.dividend_total, "
            "f.buyback_amount, f.buyback_retired_amount, vm.payout_ratio "
            "FROM financials f "
            "LEFT JOIN valuation_metrics vm ON vm.corp_code = f.corp_code "
            "AND vm.year = f.year AND vm.quarter = f.quarter "
            "WHERE f.year < :yr OR (f.year = :yr AND f.quarter < 4) "
            "ORDER BY f.corp_code, f.year, f.quarter"
        ),
        {"yr": as_of_year},
    ).mappings().all()
    names = {
        r["corp_code"]: r
        for r in session.execute(
            select(Company.corp_code, Company.corp_name, Company.sector).order_by(Company.corp_code)
        ).mappings()
    }
    status = {
        r["corp_code"]: r["buyback_status"]
        for r in session.execute(
            select(ValueupScore.corp_code, ValueupScore.buyback_status)
            .where(ValueupScore.as_of == as_of)
        ).mappings()
    }
    out: list[dict[str, Any]] = []
    for f in fin:
        c = names.get(f["corp_code"])
        if c is None:
            continue
        out.append({
            "corp_code": f["corp_code"], "corp_name": c["corp_name"],
            "sector": c["sector"], "as_of": as_of,
            "year": f["year"], "quarter": f["quarter"],
            "dividend_total": f["dividend_total"],
            "payout_ratio": f["payout_ratio"],
            "buyback_amount": f["buyback_amount"],
            "buyback_retired_amount": f["buyback_retired_amount"],
            "buyback_status": status.get(f["corp_code"]),
        })
    return out


def macro_rows(session: Session) -> list[dict[str, Any]]:
    """매크로 레이어: macro_indicator 전체(본질이 시계열이라 as_of 스냅숏 예외 —
    3.4의 시계열 차트와 같은 근거)."""
    rows = session.execute(
        select(
            MacroIndicator.indicator, MacroIndicator.date,
            MacroIndicator.value, MacroIndicator.frequency,
        ).order_by(MacroIndicator.indicator, MacroIndicator.date)
    ).mappings().all()
    return [dict(r) for r in rows]

```

## `app/export/tableau.py`

```python
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

```

## `tests/test_export_tableau.py`

```python
"""Story 3.5 — Tableau CSV export 검증 (SQLite in-memory).

핵심 계약 3종: ① 단일 as_of 수렴 ② null → 빈 셀(0 세탁 금지) ③ 빈 스코어면
빈 CSV 대신 명시적 에러. + look-ahead 부분 차단 규칙이 export에도 동일 적용.
"""

from __future__ import annotations

import csv

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.export.tableau import NoScoreDataError, export_all
from app.models import Base, Company, MacroIndicator, MnaScore, ValueupScore
from app.sql_views import CREATE_VALUATION_METRICS

AS_OF_OLD = "2026-07-01"
AS_OF = "2026-07-13"


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.connect() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))
        conn.commit()
    return eng


@pytest.fixture()
def session(engine):
    s = sessionmaker(bind=engine, future=True)()
    yield s
    s.close()


def _seed(s: Session) -> None:
    for code, name, market, sector in (
        ("00000001", "알파", "KOSPI", "전자"),
        ("00000002", "베타", "KOSPI", "은행"),
        ("00000003", "감마", "KOSDAQ", "바이오"),
    ):
        s.add(Company(corp_code=code, corp_name=name, market=market, sector=sector))
    s.execute(text(
        "INSERT INTO financials (corp_code, year, quarter, revenue, net_income, equity, "
        "total_assets, total_liabilities, operating_income, dividend_total) VALUES "
        "('00000001', 2025, 3, 1000, 100, 1000, 3000, 1000, 120, 30), "
        # 같은 해(2026) 사업보고서 — look-ahead 배제 대상
        "('00000001', 2026, 4, 9999, 9999, 9999, 9999, 9999, 9999, 9999), "
        # 베타: net_income null → payout_ratio null(뷰 CASE) — null 빈 셀 검증용
        "('00000002', 2025, 3, 500, NULL, 500, 1500, 500, 60, NULL), "
        "('00000003', 2025, 3, 300, 60, 300, 900, 300, 70, 10)"
    ))
    s.execute(text(
        "INSERT INTO prices (corp_code, date, close, volume, trading_value, market_cap) VALUES "
        "('00000001', '2025-12-31', 1000, 1, 1, 800), "
        "('00000002', '2025-12-31', 1000, 1, 1, 400), "
        "('00000003', '2025-12-31', 1000, 1, 1, 600)"
    ))
    # 스코어: 구 as_of 행(섞이면 안 됨) + 최신 as_of 행
    s.add(ValueupScore(corp_code="00000001", as_of=AS_OF_OLD, execution_score=10.0,
                       washing_flag=True, buyback_status="none"))
    s.add(ValueupScore(corp_code="00000001", as_of=AS_OF, execution_score=72.5,
                       achievement_rate=0.0, washing_flag=False, buyback_status="retired"))
    # 감마: execution_score null(엔진이 판단불가로 남긴 케이스)
    s.add(ValueupScore(corp_code="00000003", as_of=AS_OF, execution_score=None,
                       washing_flag=None, buyback_status=None))
    s.add(MnaScore(corp_code="00000001", as_of=AS_OF, mna_target_score=71.0,
                   valuation_score=0.89, population_basis="sector"))
    s.add(MacroIndicator(indicator="base_rate", date="2026-07-01", value=2.5, frequency="M"))
    s.add(MacroIndicator(indicator="usd_krw", date="2026-07-01", value=None, frequency="D"))
    s.commit()


def _read(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_export_writes_five_views_with_single_as_of(session, tmp_path):
    _seed(session)
    counts = export_all(session, tmp_path)
    assert set(counts) == {
        "valueup_scores", "sector_valuation_map", "roe_pbr_scatter",
        "dividend_buyback", "macro_layer",
    }
    # 단일 as_of: 최신(AS_OF)만, 구 as_of 행 미혼입
    vs = _read(tmp_path / "valueup_scores.csv")
    assert {r["as_of"] for r in vs} == {AS_OF}
    alpha = next(r for r in vs if r["corp_code"] == "00000001")
    assert alpha["execution_score"] == "72.5"  # 구 as_of의 10.0이 아님
    assert alpha["washing_flag"] == "false"  # bool 소문자 통일


def test_null_stays_empty_cell_not_zero(session, tmp_path):
    _seed(session)
    export_all(session, tmp_path)
    vs = _read(tmp_path / "valueup_scores.csv")
    gamma = next(r for r in vs if r["corp_code"] == "00000003")
    assert gamma["execution_score"] == ""  # null → 빈 셀(0 아님)
    assert gamma["washing_flag"] == ""
    # 정상값 0은 보존(0 falsy 세탁 금지 — 3.4 High 회귀)
    alpha = next(r for r in vs if r["corp_code"] == "00000001")
    assert alpha["achievement_rate"] == "0.0"
    # payout_ratio null(net_income null) → 빈 셀
    db = _read(tmp_path / "dividend_buyback.csv")
    beta = next(r for r in db if r["corp_code"] == "00000002")
    assert beta["payout_ratio"] == ""
    assert beta["dividend_total"] == ""


def test_lookahead_partial_block_applies(session, tmp_path):
    _seed(session)
    export_all(session, tmp_path)
    scatter = _read(tmp_path / "roe_pbr_scatter.csv")
    alpha = next(r for r in scatter if r["corp_code"] == "00000001")
    # 같은 해(2026) 사업보고서(quarter=4)가 아니라 2025Q3이 최신으로 선택돼야 함
    assert (alpha["metrics_year"], alpha["metrics_quarter"]) == ("2025", "3")
    db = _read(tmp_path / "dividend_buyback.csv")
    assert not any(r["corp_code"] == "00000001" and r["year"] == "2026" for r in db)


def test_mna_absence_exposed_not_hidden(session, tmp_path):
    """mna_score 없는 종목(은행 등)도 업종맵에 남고 스코어만 빈 셀 — 조인 세탁 금지."""
    _seed(session)
    export_all(session, tmp_path)
    smap = _read(tmp_path / "sector_valuation_map.csv")
    beta = next(r for r in smap if r["corp_code"] == "00000002")
    assert beta["mna_target_score"] == ""
    assert beta["sector"] == "은행"


def test_empty_scores_raise_instead_of_empty_csv(session, tmp_path):
    with pytest.raises(NoScoreDataError):
        export_all(session, tmp_path)
    assert not list(tmp_path.iterdir())  # 파일을 하나도 쓰지 않음


def test_macro_layer_full_series(session, tmp_path):
    _seed(session)
    export_all(session, tmp_path)
    macro = _read(tmp_path / "macro_layer.csv")
    assert len(macro) == 2
    usd = next(r for r in macro if r["indicator"] == "usd_krw")
    assert usd["value"] == ""  # 매크로 결측도 빈 셀

```

## `docs/implementation-artifacts/tableau-spec-3-5.md`

```markdown
# Tableau 대시보드 구성 스펙 (Story 3.5)

Tableau Public에서 아래 순서대로 조립한다. 데이터 소스는 `exports/tableau/*.csv`
(생성: `python -m app.export.tableau`, 갱신 시 재실행 후 Tableau에서 Data → Refresh).
모든 CSV는 UTF-8 BOM이라 한글 종목명이 그대로 열린다.

공통 규칙
- **null = 빈 셀**은 "판단 불가/미집계"다. 0으로 읽지 말 것 — 집계 시 Tableau 기본이
  null 제외라 그대로 두면 되고, 색·라벨로 표시할 땐 회색(#9ca3af) 중립 처리(3.2 Figma
  null 시각언어·3.4 프론트와 동일).
- `washing_flag`는 `"true"/"false"/빈칸` 3값 — 필터 생성 시 빈칸을 "판정불가"로 별도 표기.
- `sector`는 DART induty 코드(예: 24213) — 표시용 업종명 매핑은 프로젝트 스코프 밖
  (API도 코드 그대로 반환). 필요하면 Tableau 별칭(Aliases)으로 수동 지정.
- 모든 스코어 계열 CSV는 **단일 as_of**(파일 내 `as_of` 컬럼)로 뽑혀 있다 —
  대시보드 제목에 as_of를 표기해 기준일을 못 박을 것.

## 뷰 1 — 밸류업 점수 (valueup_scores.csv)

- 차트: 가로 막대(종목별 execution_score 내림차순).
- 행: corp_name / 열: execution_score.
- 색: washing_flag (true=경고색 #dc2626, false=기본 #2563eb, 빈칸=회색).
- 툴팁: achievement_rate·progress_rate·buyback_status.
- 필터: market, sector, washing_flag.

## 뷰 2 — 업종별 저평가 맵 (sector_valuation_map.csv)

- 차트: 트리맵. 그룹: sector → corp_name.
- 크기: mna_target_score (빈칸 종목은 자동 제외됨 — 별도 목록으로 "미산정 N종목" 캡션 권장).
- 색: pbr 연속 그라디언트(낮을수록 진하게 = 저평가 강조), 중앙값 1.0 기준 diverging.
- 툴팁: per·ev_ebitda·valuation_score·population_basis(모집단이 sector인지
  market_fallback인지 — 2.7의 small-N 폴백 식별 계약을 화면까지 노출).
- 필터: market.

## 뷰 3 — ROE-PBR 산점도 (roe_pbr_scatter.csv)

- 차트: 산점도. 열: roe / 행: pbr.
- 색: execution_score 연속(빈칸=회색). 모양: washing_flag.
- 참조선: pbr=1.0 (저평가 기준선), roe=8% (시장 평균 근방 — /stats/summary avg_roe 참고).
- 레이블: corp_name (겹침 시 상위 execution_score만).
- 우하단(고ROE·저PBR) 사분면이 "밸류업 스토리 후보" — 대시보드 주석으로 표기.
- 필터: market, sector.

## 뷰 4 — 배당/자사주 (dividend_buyback.csv)

- 차트: 이중축 콤보. 열: year(불연속) / 행 1: SUM(dividend_total) 막대 /
  행 2: buyback_amount+buyback_retired_amount 라인(또는 누적 막대).
- 색: buyback_status (retired=진초록, purchased_only=연두, none=회색 — 워싱 신호 위계).
- 필터: corp_name(단일 선택 권장 — 종목별 환원 추이 뷰), sector.
- 주의: dividend_total은 best-effort 수집(없으면 빈칸) — 빈 해를 "배당 0"으로 읽지 말 것.

## 매크로 레이어 (macro_layer.csv)

- 차트: 지표별 라인 4장(base_rate·bond_3y·usd_krw·leading_index), 열: date(연속) / 행: value.
- 대시보드에서 뷰 1~4 하단에 가로 스트립으로 배치 — "매크로 국면 컨텍스트"(UX-DR5).
- frequency(M/D)가 달라 축 밀도가 다름 — 지표별 개별 시트로 만들고 y축 독립.

## 대시보드 배치

```
┌─────────────────────────────────────────────┐
│ 밸류업 워싱 스크리너 — as_of 2026-07-13     │
├──────────────────────┬──────────────────────┤
│ 뷰3 ROE-PBR 산점도   │ 뷰2 업종 저평가 맵    │
├──────────────────────┼──────────────────────┤
│ 뷰1 밸류업 점수      │ 뷰4 배당/자사주       │
├──────────────────────┴──────────────────────┤
│ 매크로 스트립: 기준금리·국고3y·환율·선행지수 │
└─────────────────────────────────────────────┘
```

- 전역 필터(market·sector)를 뷰 1~4에 적용(매크로 스트립은 종목 무관이라 제외).
- 게시: Tableau Public → 워크북 저장(로컬 CSV extract가 함께 업로드됨).
  데이터 갱신 시 export 재실행 → Tableau에서 extract refresh → 재게시.

## 검증 기준 (조립 후 확인)

- 뷰 1 종목 수 = valueup_scores.csv 행수(26, 2026-07-13 기준).
- 워싱 비율 = `/stats/summary`의 washing_ratio와 일치(패리티는 export 시점에 코드로 검증됨).
- 매크로 최신값 4종 = `/stats/macro` 응답과 일치.

```

## `docs/implementation-artifacts/3-5-tableau-dashboard.md`

```markdown
---
baseline_commit: 4ca4e2b785090604702c87c3a891958f70ff67b7
---

# Story 3.5: Tableau 대시보드 연계

Status: review

## Story

As a 애널리스트,
I want Tableau에서 시장·매크로 대시보드를 보는 것,
So that 발표·리포트용 시각 자료를 얻는다.

## Acceptance Criteria (epics.md 원문)

**Given** `/stats/*`와 지표·스코어·매크로 데이터(UX-DR5)
**When** Tableau를 PostgreSQL에 연결하면
**Then** 밸류업 점수·업종별 저평가 맵·ROE-PBR 산점도·배당/자사주 4개 뷰와 ECOS 매크로 레이어가 구성되고
**And** 각 뷰가 API/DB 뷰를 소스로 갱신된다.

UX-DR5: Tableau 4개 뷰 + 매크로 레이어 — 밸류업 점수·업종 저평가 맵·ROE-PBR 산점도·배당/자사주 + ECOS 금리/환율 컨텍스트.

## ⚠️ 스토리 오너 결정 필요 사항 — AC와 실제 스택의 불일치 (dev 착수 전 필독)

에픽 AC는 **"Tableau를 PostgreSQL에 연결"**이라고 쓰여 있으나, 실측 결과 프로젝트의 실제 DB는 **SQLite**다:

- `app/config.py:34` — `database_url: SecretStr = SecretStr("sqlite:///./valueup.db")`
- `app/db.py:18` — sqlite 백엔드 분기 존재. PostgreSQL 마이그레이션은 어디에도 없음.
- 메모리·로드맵상 배포 타깃은 **Tableau Public**(무료)인데, Tableau Public은 라이브 DB 연결(PostgreSQL 포함)을 **지원하지 않는다** — 파일(CSV/Excel/Hyper extract)·Google Sheets 등 정적 소스만 가능.

**권장 해법(비용 최소·AC 정신 보존): CSV export 레이어.**
PostgreSQL 마이그레이션(과잉·다른 스토리 전부 재검증 필요)이나 유료 Tableau Desktop+ODBC 대신, DB 뷰/테이블에서 **뷰별 tidy CSV를 뽑는 export 스크립트**를 만들고 Tableau는 그 CSV를 소스로 쓴다. "각 뷰가 API/DB 뷰를 소스로 갱신된다"는 AC의 And절은 "export 스크립트 재실행 → CSV 갱신 → Tableau 새로고침"으로 충족(소스가 DB 뷰인 것은 동일, 전달 매체만 파일). AC의 "PostgreSQL에 연결하면" 문구는 이 스토리에서 **의도적 일탈**로 기록하고 근거를 남길 것 — 1.2/1.3/1.5(credit lab)와 같은 "스토리오너 재량 결정 + 근거 문서화" 패턴.

**Tableau 워크북 자체는 GUI 산출물**이라 AI가 코드로 완성할 수 없다. 이 스토리의 dev 산출물은 ①export 스크립트+CSV ②뷰별 구성 스펙 문서(필드·차트타입·필터·색상 규칙) ③검증 테스트까지이고, Tableau Public에서 워크북을 실제로 조립·게시하는 것은 사용자 수작업(스펙 문서가 그 가이드)이다. 이 분업을 Completion Notes에 명시할 것.

## Dev 구현 가이드

### 산출물 1 — Export 스크립트: `pipelines/export_tableau.py` (NEW)

CLI로 실행하면 `exports/tableau/`(gitignore 추가)에 뷰별 CSV 4~5개를 쓴다. **AD-2 준수: SQL 직접 접근 금지 — repository 레이어를 통해 조회**하거나, 불가피하면 이 스크립트를 "수집·배치 레이어"(ingest 계열과 동급)로 규정하고 read-only SELECT만 수행함을 문서화(AD-3/AD-4/AD-10의 writer 제약과 무관한 읽기 전용 경로임을 명시). 어느 쪽이든 근거를 스토리에 기록.

뷰별 CSV 스키마(tidy, 1행=1관측):

1. **`valueup_scores.csv`** (밸류업 점수 뷰): corp_code, corp_name, market, sector, as_of, execution_score, achievement_rate, progress_rate, washing_flag, buyback_status — `valueup_score` ⋈ `company`
2. **`sector_valuation_map.csv`** (업종별 저평가 맵): sector, market, corp_code, corp_name, pbr, per, ev_ebitda, mna_target_score, valuation_score — `valuation_metrics`(최신 year/quarter) ⋈ `company` ⋈ `mna_score`. 업종별 트리맵/히트맵용
3. **`roe_pbr_scatter.csv`** (ROE-PBR 산점도): corp_code, corp_name, market, sector, roe, pbr, execution_score(색), washing_flag(모양), market_cap 대용 없음 주의 — `valuation_metrics` 최신 행 ⋈ `company` ⋈ `valueup_score`
4. **`dividend_buyback.csv`** (배당/자사주): corp_code, corp_name, sector, year, payout_ratio, dividend_total(financials에서), buyback_executed, buyback_retired, buyback_status — `financials`+`valuation_metrics` ⋈ `valueup_score`
5. **`macro_layer.csv`** (ECOS 매크로 레이어): indicator, date, value, frequency — `macro_indicator` 전체(3,369행 실측)

**null 정직성 계약(이 프로젝트 1.8부터의 핵심 원칙)**: null은 빈 셀로 내보내고 0으로 채우지 말 것. 3.4 리뷰에서 "0 falsy → '—' 세탁"이 High로 잡혔던 프로젝트다 — export에서 null→0 세탁이 나오면 같은 계열의 반려 사유.

### 산출물 2 — 뷰 구성 스펙 문서: `docs/implementation-artifacts/tableau-spec-3-5.md` (NEW)

4개 뷰+매크로 레이어 각각에 대해: 소스 CSV, 차트 타입, 행/열 선반 필드, 색/크기/모양 인코딩, 필터(시장·업종·워싱), null 표시 규칙(3.2 Figma에서 확정한 null 시각언어와 일관), 대시보드 배치. 사용자가 Tableau Public에서 그대로 조립할 수 있는 수준으로.

### 산출물 3 — 검증

- pytest: export 함수 단위 테스트(합성 DB로 스키마·null 보존·최신 as_of 선택 검증). 기존 231 passed 회귀 0 유지.
- 실데이터 실행: `valueup.db`(valueup_score 26·mna_score 31·valuation_metrics 66·macro 3,369행 실측)로 CSV 생성 후, 대표 수치가 `/stats/*` API 응답과 일치하는지 대조(예: washing_ratio를 CSV에서 재계산 → `/stats/summary`와 비교). **API-CSV 패리티가 "각 뷰가 API/DB 뷰를 소스로 갱신된다" AC의 실증**이다.

### 아키텍처 가드레일

- AD-1: 파생지표는 `valuation_metrics` VIEW에서만 — export가 지표를 재계산하지 말 것(뷰를 SELECT).
- AD-2: 레이어 의존 단방향. export 스크립트는 routers를 import하지 말 것.
- AD-4/AD-10: valueup_score·mna_score는 읽기 전용.
- AD-8: as_of 신선도 — 스코어 계열은 최신 as_of 행만 exports에 포함하고, 어느 as_of인지 CSV에 컬럼으로 남길 것(3.4의 as_of 시점 혼합 High 리뷰와 같은 함정: **뷰별 CSV가 서로 다른 기준일로 뽑히면 대시보드에서 시점이 섞인다** — 단일 as_of로 수렴시키고 스크립트 로그에 명시).

### 이전 스토리 인텔리전스 (3-1, 3-4)

- 3-1이 만든 `/stats/market-comparison`·`/stats/summary`·`/stats/macro`가 "Tableau가 물릴 집계 JSON"으로 이미 설계됨 — export 검증의 대조 기준으로 활용.
- 3-4 리뷰 교훈 3종이 이 스토리에 그대로 적용: ①as_of 혼합 금지 ②null≠0 세탁 금지 ③에러를 빈 데이터로 세탁 금지(export 실패 시 빈 CSV를 쓰지 말고 명시적 에러).
- 3-3/3-4에서 corp_code는 `^\d{8}$` 패턴이 계약.
- 프로젝트 관례: 구현 → status=review → **GPT 교차리뷰**(코드 verbatim 전달, 축약 금지 — epic-1 액션아이템) → 반영 → done.

### 관련 테이블 실측 스키마 (2026-07-14, valueup.db)

- `company(corp_code, stock_code, corp_name, market, sector)`
- `valuation_metrics(corp_code, year, quarter, roe, roa, pbr, per, ev_ebitda, debt_ratio, payout_ratio, net_cash, ebitda_margin, yoy_revenue_growth, yoy_income_growth)` — VIEW, 66행
- `valueup_score(…, as_of, achievement_rate, progress_rate, execution_score, washing_flag, buyback_executed, buyback_retired, buyback_status, target_roe, actual_roe, roe_gap)` — 26행
- `mna_score(…, as_of, mna_target_score, valuation_score, capacity_score, ownership_score, macro_score, population_basis)` — 31행
- `macro_indicator(indicator, date, value, frequency)` — 3,369행

## Dev Agent Record

### Agent Model Used

claude-fable-5 (bmad-create-story + bmad-dev-story, 2026-07-14)

### Debug Log References

- 스크립트 위치를 스토리 가이드의 `pipelines/export_tableau.py`에서 `app/export/tableau.py`로 변경 — 이 repo에 pipelines/ 디렉터리가 없고(credit lab 관례가 스토리에 새어 들어간 것), ingest와 동급의 배치 레이어로 app/ 안에 두는 것이 기존 구조와 정합. SQL은 전부 신규 `app/repositories/export.py` 경유(AD-2).
- look-ahead 부분 차단 규칙(`year<yr OR (year=yr AND quarter<4)`)을 screening/stats와 동일하게 적용 — 규칙이 갈라지면 CSV-API 패리티가 깨지므로 5번째 사용처로 독립 작성(공통화는 deferred-work 기존 항목 유지).
- CSV는 UTF-8 BOM(한글 종목명 Tableau/Excel 호환), bool은 소문자 통일, None은 csv 모듈 기본으로 빈 셀.

### Completion Notes List

- **산출물 3종 완료**: ① `app/export/tableau.py`(CLI: `python -m app.export.tableau`) + `app/repositories/export.py` — 뷰별 tidy CSV 5개 생성 ② `docs/implementation-artifacts/tableau-spec-3-5.md` — 뷰별 차트타입·선반·인코딩·필터·null 규칙·대시보드 배치·게시 절차 ③ 테스트 6종.
- **계약 3종을 테스트로 고정**: 단일 as_of 수렴(구 as_of 행 미혼입 실증), null→빈 셀 + 정상값 0 보존(3.4 High 회귀 방지), 빈 스코어 시 NoScoreDataError(파일 0개 — 빈 CSV 세탁 금지). + look-ahead 배제·mna 부재 정직 노출·매크로 결측.
- **실데이터 실행(valueup.db)**: as_of=2026-07-13, valueup_scores 26행·sector_valuation_map 33행·roe_pbr_scatter 31행·dividend_buyback 66행·macro_layer 3,369행.
- **API-CSV 패리티 실증(AC "각 뷰가 API/DB 뷰를 소스로 갱신" 검증)**: `/stats/summary` — as_of·판정모수 19·워싱 0·washing_ratio 0.0이 CSV 재계산과 일치. `/stats/macro` — 최신값 4종(base_rate 2.5, bond_3y 3.768, usd_krw 1504.2, leading_index 104.8) 전부 CSV와 일치.
- pytest **237 passed**(기존 231 + 신규 6, 회귀 0).
- **AC "PostgreSQL 연결" 의도적 일탈**: Tableau Public은 라이브 DB 연결 미지원 + 실스택 SQLite — CSV export 레이어로 대체(스토리 상단 결정 사항 참조). Tableau 워크북 조립·게시는 GUI 수작업(spec 문서가 가이드) — dev 산출물 범위 밖.
- 알려진 한계: sector가 DART induty 코드 그대로(API와 동일) — 표시용 업종명 매핑은 스코프 밖, Tableau 별칭으로 수동 처리 가능(spec에 기재).

### File List

- `app/repositories/export.py` (NEW: 뷰별 read-only 조회 5종)
- `app/export/__init__.py`·`app/export/tableau.py` (NEW: CSV export CLI)
- `tests/test_export_tableau.py` (NEW: 6 tests)
- `docs/implementation-artifacts/tableau-spec-3-5.md` (NEW: Tableau 조립 스펙)
- `.gitignore` (UPDATE: exports/ 제외)
- `exports/tableau/*.csv` (생성물, gitignore — 재생성 가능)

## Change Log

- 2026-07-14: Story 3.5 생성 — AC의 "PostgreSQL 연결"과 실제 스택(SQLite+Tableau Public) 불일치 발견, CSV export 레이어로 해소하는 방향 제시(스토리오너 결정 필요 표기). 산출물 3종(export 스크립트·뷰 스펙 문서·API-CSV 패리티 검증) 정의.
- 2026-07-14: Story 3.5 구현 — export 레이어(repository+CLI)·테스트 6종·Tableau 스펙 문서. 실데이터 5개 CSV 생성 + /stats/* 패리티 실증. 237 passed. Status → review(GPT 교차리뷰 대기).

```
