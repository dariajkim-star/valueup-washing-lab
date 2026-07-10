# 코드 리뷰 요청 — 밸류업 워싱 스크리너 Story 1.7 (밸류에이션 지표 SQL VIEW + /metrics API)

너는 엄격한(adversarial) 시니어 코드 리뷰어야. 아래 스토리/AC, 아키텍처 제약, 코드를 보고
버그·규약 위반·엣지케이스·SQL 정확성 문제를 찾아줘. [High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정. 칭찬 생략, 없으면 "clean".

**이번 핵심 = SQL VIEW의 정확성·이식성 + API 레이어**라 특히:
- 뷰 SQL의 정확성: 최신주가 상관서브쿼리(LEFT JOIN에 서브쿼리), LAG 윈도우(연간 데이터 가정), NULLIF 0방어, float 강제(*100.0), COALESCE(감가상각비) EBIT 근사
- 이식성: SQLite/PostgreSQL 양쪽 동작 주장(ROUND·WINDOW·상관서브쿼리 방언 차이)
- 과거 행에 '최신' 시총을 붙이는 조인의 의미(historical PBR 왜곡)
- text() 원시 SQL 인젝션/파라미터 바인딩 안전성
- /metrics 필터·정렬·페이지네이션·N+1·성능(뷰가 매 조회 재계산)
- 레이어 규약(AD-2), 응답 봉투(AD-6)

## 스토리 & AC
- As a 애널리스트, ROE·ROA·PBR·PER·EV/EBITDA·부채비율·배당성향·YoY를 SQL VIEW로 계산·조회.
- AC1: valuation_metrics VIEW(마이그레이션 0005), 지표는 DB뷰가 계산(AD-1)
- AC2~4: 최신주가 기준 지표, EV/EBITDA=(시총+순부채)/(영업이익+감가상각비), YoY=LAG, NULLIF 0방어
- AC5: SQLite·PostgreSQL 이식성(DISTINCT ON 미사용)
- AC6: GET /metrics 봉투(items,total,page,size), 필터 market·sector·max_pbr·min_roe·max_debt_ratio
- AC7: routers→services→repositories(AD-2)

## 아키텍처 제약
- AD-1 지표=DB VIEW 계산(파이썬 금지), AD-2 레이어 단방향, AD-6 응답봉투, AD-10 net_cash·ebitda_margin·ev_ebitda는 M&A 엔진 입력.

## 변경 코드

### `app/sql_views.py`
```python
"""SQL VIEW 정의 (마이그레이션·테스트 공용).

valuation_metrics: 지표를 앱코드가 아니라 DB VIEW로 계산(AD-1).
이식성: SQLite(개발)·PostgreSQL(운영) 모두 동작하도록 작성.
  - 최신 주가: DISTINCT ON(PG전용) 대신 상관 서브쿼리(MAX(date)).
  - float: *100.0 / *1.0 로 정수나눗셈 방지, NULLIF로 0방어.
  - YoY: LAG 윈도우 함수(연간 데이터 → 전년).
"""

from __future__ import annotations

VALUATION_METRICS_VIEW = "valuation_metrics"

CREATE_VALUATION_METRICS = f"""
CREATE VIEW {VALUATION_METRICS_VIEW} AS
SELECT
    f.corp_code,
    f.year,
    f.quarter,
    ROUND(f.net_income * 100.0 / NULLIF(f.equity, 0), 2)                           AS roe,
    ROUND(f.net_income * 100.0 / NULLIF(f.total_assets, 0), 2)                     AS roa,
    ROUND(lp.market_cap * 1.0 / NULLIF(f.equity, 0), 2)                            AS pbr,
    ROUND(lp.market_cap * 1.0 / NULLIF(f.net_income, 0), 2)                        AS per,
    -- EBITDA = 영업이익 + 감가상각비. DART 전체재무제표에 감가상각비가 없는 경우가 많아
    -- COALESCE(...,0)으로 EBIT 근사(감가상각비 있으면 정확한 EBITDA).
    ROUND((lp.market_cap + f.total_debt - f.cash) * 1.0
          / NULLIF(f.operating_income + COALESCE(f.depreciation, 0), 0), 2)        AS ev_ebitda,
    ROUND(f.total_liabilities * 100.0 / NULLIF(f.equity, 0), 2)                    AS debt_ratio,
    ROUND(f.dividend_total * 100.0 / NULLIF(f.net_income, 0), 2)                   AS payout_ratio,
    (f.cash - f.total_debt)                                                        AS net_cash,
    ROUND((f.operating_income + COALESCE(f.depreciation, 0)) * 100.0
          / NULLIF(f.revenue, 0), 2)                                              AS ebitda_margin,
    ROUND((f.revenue - LAG(f.revenue) OVER w) * 100.0
          / NULLIF(LAG(f.revenue) OVER w, 0), 2)                                   AS yoy_revenue_growth,
    ROUND((f.net_income - LAG(f.net_income) OVER w) * 100.0
          / NULLIF(LAG(f.net_income) OVER w, 0), 2)                                AS yoy_income_growth
FROM financials f
LEFT JOIN prices lp
       ON lp.corp_code = f.corp_code
      AND lp.date = (SELECT MAX(p2.date) FROM prices p2 WHERE p2.corp_code = f.corp_code)
WINDOW w AS (PARTITION BY f.corp_code ORDER BY f.year, f.quarter)
""".strip()

DROP_VALUATION_METRICS = f"DROP VIEW IF EXISTS {VALUATION_METRICS_VIEW}"
```

### `alembic/versions/0005_valuation_metrics_view.py`
```python
"""valuation_metrics SQL VIEW

Revision ID: 0005_valuation_metrics_view
Revises: 0004_macro
Create Date: 2026-07-08
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.sql_views import CREATE_VALUATION_METRICS, DROP_VALUATION_METRICS

revision: str = "0005_valuation_metrics_view"
down_revision: str | None = "0004_macro"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(CREATE_VALUATION_METRICS)


def downgrade() -> None:
    op.execute(DROP_VALUATION_METRICS)
```

### `app/schemas.py`
```python
"""API 응답 pydantic 스키마."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """목록 응답 봉투 (AD-6)."""

    items: list[T]
    total: int
    page: int
    size: int


class MetricOut(BaseModel):
    """valuation_metrics 뷰 + company 조인 결과."""

    corp_code: str
    corp_name: str | None = None
    market: str | None = None
    sector: str | None = None
    year: int
    quarter: int
    roe: float | None = None
    roa: float | None = None
    pbr: float | None = None
    per: float | None = None
    ev_ebitda: float | None = None
    debt_ratio: float | None = None
    payout_ratio: float | None = None
    net_cash: int | None = None
    ebitda_margin: float | None = None
    yoy_revenue_growth: float | None = None
    yoy_income_growth: float | None = None
```

### `app/repositories/metrics.py`
```python
"""valuation_metrics 뷰 조회 저장소 (AD-2: SQL은 여기서만).

뷰(지표) + company(표시·필터) 조인. 필터·정렬·페이지네이션.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

_BASE_SELECT = """
SELECT vm.corp_code, c.corp_name, c.market, c.sector,
       vm.year, vm.quarter, vm.roe, vm.roa, vm.pbr, vm.per, vm.ev_ebitda,
       vm.debt_ratio, vm.payout_ratio, vm.net_cash, vm.ebitda_margin,
       vm.yoy_revenue_growth, vm.yoy_income_growth
FROM valuation_metrics vm
JOIN company c ON c.corp_code = vm.corp_code
"""


def _where(filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if filters.get("market"):
        clauses.append("c.market = :market")
        params["market"] = filters["market"]
    if filters.get("sector"):
        clauses.append("c.sector = :sector")
        params["sector"] = filters["sector"]
    if filters.get("max_pbr") is not None:
        clauses.append("vm.pbr <= :max_pbr")
        params["max_pbr"] = filters["max_pbr"]
    if filters.get("min_roe") is not None:
        clauses.append("vm.roe >= :min_roe")
        params["min_roe"] = filters["min_roe"]
    if filters.get("max_debt_ratio") is not None:
        clauses.append("vm.debt_ratio <= :max_debt_ratio")
        params["max_debt_ratio"] = filters["max_debt_ratio"]
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def list_metrics(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> tuple[list[dict], int]:
    where, params = _where(filters)
    total = session.execute(
        text(f"SELECT COUNT(*) FROM valuation_metrics vm JOIN company c "
             f"ON c.corp_code = vm.corp_code{where}"),
        params,
    ).scalar_one()
    rows = session.execute(
        text(
            _BASE_SELECT + where
            + " ORDER BY vm.corp_code, vm.year, vm.quarter"
            + " LIMIT :limit OFFSET :offset"
        ),
        {**params, "limit": size, "offset": (page - 1) * size},
    ).mappings().all()
    return [dict(r) for r in rows], total


def metrics_by_corp(session: Session, corp_code: str) -> list[dict]:
    rows = session.execute(
        text(_BASE_SELECT + " WHERE vm.corp_code = :cc ORDER BY vm.year, vm.quarter"),
        {"cc": corp_code},
    ).mappings().all()
    return [dict(r) for r in rows]
```

### `app/services/metrics.py`
```python
"""지표 조회 유스케이스 (routers→services→repositories, AD-2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.repositories import metrics as repo
from app.schemas import MetricOut, Page


def list_metrics(
    session: Session, filters: dict[str, Any], page: int, size: int
) -> Page[MetricOut]:
    rows, total = repo.list_metrics(session, filters, page, size)
    return Page(
        items=[MetricOut(**r) for r in rows], total=total, page=page, size=size
    )


def metrics_by_corp(session: Session, corp_code: str) -> list[MetricOut]:
    return [MetricOut(**r) for r in repo.metrics_by_corp(session, corp_code)]
```

### `app/routers/metrics.py`
```python
"""/metrics 라우터 — 밸류에이션 지표 조회 (HTTP 경계, AD-2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import MetricOut, Page
from app.services import metrics as service

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=Page[MetricOut])
def list_metrics(
    market: str | None = None,
    sector: str | None = None,
    max_pbr: float | None = None,
    min_roe: float | None = None,
    max_debt_ratio: float | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[MetricOut]:
    filters = {
        "market": market, "sector": sector, "max_pbr": max_pbr,
        "min_roe": min_roe, "max_debt_ratio": max_debt_ratio,
    }
    return service.list_metrics(db, filters, page, size)


@router.get("/{corp_code}", response_model=list[MetricOut])
def metrics_by_corp(corp_code: str, db: Session = Depends(get_db)) -> list[MetricOut]:
    return service.metrics_by_corp(db, corp_code)
```

### `tests/test_metrics.py`
```python
"""Story 1.7 — valuation_metrics SQL VIEW 계산 + /metrics API 검증."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Company, Financial, Price
from app.sql_views import CREATE_VALUATION_METRICS


@pytest.fixture()
def engine():
    # StaticPool + check_same_thread=False: in-memory DB를 스레드 간 공유(TestClient 워커 스레드 대응)
    eng = create_engine(
        "sqlite:///:memory:", future=True,
        poolclass=StaticPool, connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        conn.execute(text(CREATE_VALUATION_METRICS))  # 뷰 생성(마이그레이션과 동일 SQL)
    return eng


def _seed(session: Session) -> None:
    session.add(Company(corp_code="00000001", stock_code="000001",
                        corp_name="테스트", market="KOSPI", sector="반도체"))
    # 2023: 순이익 100, 자본 1000, 자산 2000, 부채 1000, 매출 500,
    #       영업이익 120, 감가 30, 현금 200, 차입금 400, 배당 20
    session.add(Financial(corp_code="00000001", year=2023, quarter=4,
        revenue=500, net_income=100, operating_income=120, depreciation=30,
        equity=1000, total_assets=2000, total_liabilities=1000, cash=200,
        total_debt=400, dividend_total=20))
    # 2024: 매출 600, 순이익 150 (YoY 매출 +20%, 순이익 +50%)
    session.add(Financial(corp_code="00000001", year=2024, quarter=4,
        revenue=600, net_income=150, operating_income=180, depreciation=30,
        equity=1200, total_assets=2200, total_liabilities=1000, cash=250,
        total_debt=400, dividend_total=30))
    # 최신 시총 3000
    session.add(Price(corp_code="00000001", date="2024-12-30", close=100,
                      market_cap=3000, volume=10, trading_value=1000))
    session.commit()


def test_view_computes_metrics(engine) -> None:
    """AC2/AC3/AC4: 뷰가 ROE·PBR·EV/EBITDA·YoY를 정확히 계산."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
        rows = s.execute(text(
            "SELECT * FROM valuation_metrics WHERE year=2024")).mappings().one()
    # ROE = 150/1200*100 = 12.5
    assert rows["roe"] == 12.5
    # PBR = 3000/1200 = 2.5
    assert rows["pbr"] == 2.5
    # PER = 3000/150 = 20
    assert rows["per"] == 20.0
    # EV/EBITDA = (3000 + 400 - 250)/(180+30) = 3150/210 = 15
    assert rows["ev_ebitda"] == 15.0
    # net_cash = 250-400 = -150
    assert rows["net_cash"] == -150
    # YoY 매출 = (600-500)/500*100 = 20, 순이익 = (150-100)/100*100 = 50
    assert rows["yoy_revenue_growth"] == 20.0
    assert rows["yoy_income_growth"] == 50.0


def test_view_null_safe(engine) -> None:
    """NFR2: 0 나눗셈은 NULLIF로 방어(null)."""
    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        s.add(Company(corp_code="00000002", corp_name="영값"))
        s.add(Financial(corp_code="00000002", year=2024, quarter=4,
              revenue=0, net_income=0, equity=0, total_assets=0))
        s.commit()
        row = s.execute(text(
            "SELECT roe, pbr FROM valuation_metrics WHERE corp_code='00000002'"
        )).mappings().one()
    assert row["roe"] is None  # equity 0 → NULLIF → null
    assert row["pbr"] is None


def test_metrics_api(engine, monkeypatch) -> None:
    """AC6: /metrics API가 봉투로 반환하고 필터가 동작."""
    from fastapi.testclient import TestClient

    import app.db as db_module

    Session_ = sessionmaker(bind=engine)
    with Session_() as s:
        _seed(s)
    monkeypatch.setattr(db_module, "SessionLocal", Session_)
    # get_db가 위 SessionLocal을 쓰도록
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)

    r = client.get("/metrics", params={"min_roe": 10})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "size"}
    assert body["total"] >= 1
    assert all(i["roe"] >= 10 for i in body["items"] if i["roe"] is not None)
```

## 이미 알려진 것 (중복 지적 불필요)
- 감가상각비가 DART 전체재무제표에 없어 EBITDA→EBIT 근사(COALESCE 0)는 의도된 폴백, deferred로 기록됨.
- 연간 데이터라 YoY는 LAG(1)=전년(운영 분기데이터면 LAG(4)).
- 뷰는 Base.metadata 밖(raw SQL). 테스트는 StaticPool로 in-memory 공유.
- 라이브 검증됨: 삼성·하이닉스 실지표(pytest 39 passed).
- 과거 행에 최신 시총 붙는 점은 인지함(deferred).

## 출력 형식
[High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정
