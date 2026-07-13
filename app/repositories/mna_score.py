"""mna_score 배치 입력 조회 + 멱등 upsert 저장소 (AD-2: SQL은 여기서만).

mna_engine(app/analysis/mna_engine.py)의 유일한 DB 접근 지점. 2.1(gap_engine, 종목별 단건
조회)과 달리 **cross-sectional 백분위**라 전체 모집단을 배치로 한 번에 가져온다 — 종목 루프
안에서 단건 쿼리하면 N+1이자 설계 오류(한 종목의 점수가 전체 분포에 의존).

look-ahead 부분차단은 2.1(valueup_score.py)과 동일 규칙: 같은 연도의 사업보고서(quarter=4)는
그 해 안에 공시될 수 없으므로(통상 다음해 3월) 배제 — `year<yr OR (year=yr AND quarter<4)`.
1~3분기 동일연도 시차는 공통 defer(deferred-work.md 2-1 섹션).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Company, MacroIndicator, MnaScore, Ownership


def list_all_corp_codes(session: Session) -> list[str]:
    """전 종목 corp_code 목록(run()의 corp_codes 기본값)."""
    return list(session.scalars(select(Company.corp_code)).all())


def all_company_sectors(session: Session) -> dict[str, str | None]:
    """전 종목 corp_code → sector(DART induty_code). 2.7 버킷 택소노미 입력."""
    rows = session.execute(select(Company.corp_code, Company.sector)).all()
    return {code: sector for code, sector in rows}


def all_latest_metrics(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """전 종목의 as_of 시점 최신 (year,quarter) valuation_metrics 행(배치).

    corp_code → {ev_ebitda, pbr, debt_ratio, net_cash, ebitda_margin}.
    look-ahead 배제 후 corp별 최신 1행을 Python에서 선택(정렬된 결과 첫 등장 유지 —
    SQLite/PostgreSQL 양쪽에서 동일 동작, 데이터 규모상 충분).
    """
    as_of_year = int(as_of[:4])
    rows = session.execute(
        text(
            "SELECT corp_code, ev_ebitda, pbr, debt_ratio, net_cash, ebitda_margin "
            "FROM valuation_metrics "
            "WHERE year < :yr OR (year = :yr AND quarter < 4) "
            "ORDER BY corp_code, year DESC, quarter DESC"
        ),
        {"yr": as_of_year},
    ).mappings().all()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row["corp_code"]
        if code not in latest:  # 정렬상 corp별 첫 행 = 최신
            latest[code] = {
                "ev_ebitda": row["ev_ebitda"],
                "pbr": row["pbr"],
                "debt_ratio": row["debt_ratio"],
                "net_cash": row["net_cash"],
                "ebitda_margin": row["ebitda_margin"],
            }
    return latest


def all_latest_ownership(session: Session, as_of: str) -> dict[str, dict[str, Any]]:
    """전 종목의 as_of 이전(포함) 최신 ownership 행(배치).

    corp_code → {largest_shareholder_pct, treasury_stock_pct}.
    as_of 근사치(비12월 결산 라벨오류)는 1-6 known-limitation 그대로.
    """
    stmt = (
        select(Ownership)
        .where(Ownership.as_of <= as_of)
        .order_by(Ownership.corp_code, Ownership.as_of.desc())
    )
    latest: dict[str, dict[str, Any]] = {}
    for obj in session.scalars(stmt):
        if obj.corp_code not in latest:
            latest[obj.corp_code] = {
                "largest_shareholder_pct": obj.largest_shareholder_pct,
                "treasury_stock_pct": obj.treasury_stock_pct,
            }
    return latest


def latest_macro_percentile_basis(
    session: Session, as_of: str, indicator: str = "base_rate"
) -> tuple[float | None, list[float]]:
    """(as_of 이전 최신 지표값, as_of 이전 전체 역사 시계열) — 매크로 백분위 기준.

    모집단 = as_of 이전 전체 관측값(리드 결정: 롤링 윈도우 아님, ECOS 수집 기간 길어지면
    후속 재검토). as_of 이후 관측은 look-ahead라 제외.
    """
    stmt = (
        select(MacroIndicator)
        .where(MacroIndicator.indicator == indicator, MacroIndicator.date <= as_of)
        .order_by(MacroIndicator.date.desc())
    )
    objs = list(session.scalars(stmt))
    # 현재값 = 최신 '관측 행'의 값(null이면 null 그대로 — 과거 non-null로 몰래 대체 금지,
    # 코드리뷰 2026-07-10 High: AC6 엄격 null 위반이었음). history 정제와 현재값 선택은 분리.
    current = objs[0].value if objs else None
    history = [o.value for o in objs if o.value is not None]
    return current, history


def upsert_mna_score(session: Session, rec: dict[str, Any]) -> MnaScore:
    """(corp_code, as_of) 자연키 기준 mna_score upsert.

    2.1 upsert_valueup_score와 동일 정책: 권위 있는 전체 재계산 결과이므로 null 포함 전체
    교체 + `rec[field]` 직접 인덱싱(키 누락은 프로그래밍 오류 → KeyError로 즉시 노출).
    """
    stmt = select(MnaScore).where(
        MnaScore.corp_code == rec["corp_code"], MnaScore.as_of == rec["as_of"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = MnaScore(corp_code=rec["corp_code"], as_of=rec["as_of"])
        session.add(obj)
    for field in (
        "mna_target_score", "valuation_score", "capacity_score",
        "ownership_score", "macro_score", "population_basis",
    ):
        setattr(obj, field, rec[field])
    return obj


# ── 서빙 조회 (2.5 /mna/ranking) ─────────────────────────────────────────────
# 위쪽은 mna_engine 전용 배치 입력·upsert, 아래는 API 서빙 읽기 전용(AD-10: 쓰기는 엔진만).


def latest_as_of(session: Session) -> str | None:
    """mna_score의 최신 as_of(기본 조회 기준일). 없으면 None.

    부분 실행이 latest_as_of를 오염시키는 문제는 2.4와 공통 defer(score_run 메타데이터,
    deferred-work.md) — 여기서 해결하지 않는다.
    """
    return session.scalar(select(func.max(MnaScore.as_of)))


def list_scores(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> tuple[list[dict[str, Any]], int]:
    """M&A 타겟 랭킹 서빙 조회(2.5). company 조인 + 필터 + mna_target_score 내림차순.

    2.4 list_scores와 동일 골격, 정렬 방향만 반대(인수 매력 높은 순). null 정렬은
    방언 무관 명시적 키(`IS NULL` 우선 → 값 desc → corp_code 안정 정렬)로 처리.
    sector 필터는 KSIC prefix 매칭(2.7 버킷 택소노미와 동일 단위) — 정확일치로 하면
    세분류 코드(4~5자리)를 사용자가 알 수 없어 필터가 사실상 죽는다.
    """
    conds = [MnaScore.as_of == filters["as_of"]]
    # `is not None`(truthiness 아님): 빈 문자열이 "필터 없음"으로 새는 것을 repo 층에서도
    # 차단(GPT 리뷰 Med — 1차 방어는 라우터 min_length=1의 422).
    if filters.get("market") is not None:
        conds.append(Company.market == filters["market"])
    if filters.get("sector") is not None:
        conds.append(Company.sector.startswith(filters["sector"], autoescape=True))

    base = select(MnaScore, Company).join(
        Company, Company.corp_code == MnaScore.corp_code
    ).where(*conds)

    total = session.scalar(
        select(func.count()).select_from(base.subquery())
    ) or 0
    rows = session.execute(
        base.order_by(
            MnaScore.mna_target_score.is_(None),  # null last(명시적)
            MnaScore.mna_target_score.desc(),
            MnaScore.corp_code.asc(),
        ).limit(size).offset((page - 1) * size)
    ).all()

    items = []
    for score, company in rows:
        items.append({
            "corp_code": score.corp_code,
            "corp_name": company.corp_name,
            "market": company.market,
            "sector": company.sector,
            "as_of": score.as_of,
            "mna_target_score": score.mna_target_score,
            "valuation_score": score.valuation_score,
            "capacity_score": score.capacity_score,
            "ownership_score": score.ownership_score,
            "macro_score": score.macro_score,
            "population_basis": score.population_basis,
        })
    return items, total


def delete_mna_score(session: Session, corp_code: str, as_of: str) -> None:
    """근거(입력 데이터)를 잃은 (corp_code, as_of)의 오래된 score 정리(2.1 reconciliation
    패턴). 없으면 no-op(멱등)."""
    stmt = select(MnaScore).where(
        MnaScore.corp_code == corp_code, MnaScore.as_of == as_of,
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is not None:
        session.delete(obj)
