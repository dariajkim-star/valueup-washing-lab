# 코드 리뷰 요청 — 밸류업 워싱 스크리너 Story 1.4 (매크로 수집, ECOS)

너는 엄격한(adversarial) 시니어 코드 리뷰어야. 아래 스토리/AC, 아키텍처 제약, 코드를 보고
버그·규약 위반·엣지케이스·테스트 허점을 찾아줘. [High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정. 칭찬 생략, 없으면 "clean".

**이번 핵심 = 한국은행 ECOS REST + 주기 혼재(월/일) 지표 카탈로그**라 특히:
- 키가 URL 경로에 포함되는데 예외/로그/재시도에서 키 노출 여부
- 재시도/타임아웃/rate-limit(ECOS도 일일 호출한도 있음) 방어
- 주기 혼재(월 YYYYMM / 일 YYYYMMDD) 날짜 범위 변환·경계 오류
- StatisticSearch 페이지네이션(1/1000 고정 — 1000건 초과 구간 누락 가능)
- INFO-200 외 다른 에러코드(INFO-100 키오류, ERROR-xxx) 처리
- TIME→ISO 변환(분기 Q, 반기 등 다른 포맷), 값 파싱(음수·결측)
- 멱등 upsert, None 안 덮음

## 스토리 & AC
- As a 애널리스트, ECOS에서 기준금리·국고채3년·원달러·경기선행이 macro_indicator에 적재된다.
- AC1: macro_indicator 테이블(0004), 자연키 (indicator, date)
- AC2: ecos_adapter(fetch→normalize→upsert, AD-3)로 4개 지표 적재
- AC3: 통계코드·주기(M/D)로 StatisticSearch 조회, TIME→ISO date 정규화
- AC4: (indicator, date) 멱등 upsert
- AC5: ECOS_API_KEY 미설정 시 명확한 에러
- AC6: 데이터 없음(INFO-200)은 실패 아니라 빈결과
- AC7: fixture로 정규화·멱등 단위테스트

## 아키텍처 제약
- AD-3 어댑터=macro_indicator 유일 writer/공통 인터페이스, AD-7 멱등 upsert,
- AD-10 macro_indicator는 M&A 엔진 입력(기준금리=매크로 요소), NFR2 결측 null.

## 변경 코드

### `app/models.py`
```python
"""SQLAlchemy ORM 모델.

엔티티 정식 키는 corp_code(8자리)다(AD-5). stock_code(6자리)는 company 속성.
시가총액은 company에 두지 않는다(AD-9, 시총 단일원천=prices/KRX, Story 1.3).

Story 1.2: Company, Financial 추가.
후속: prices / valueup_plan / ownership / macro_indicator / valueup_score / mna_score.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """모든 ORM 모델의 공통 Base."""

    pass


class Company(Base):
    """상장사 기본정보 (writer = dart_adapter, AD-3/AD-9)."""

    __tablename__ = "company"
    __table_args__ = (
        CheckConstraint("length(corp_code) = 8", name="ck_company_corp_code_len"),
    )

    corp_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    stock_code: Mapped[str | None] = mapped_column(String(6), index=True)
    corp_name: Mapped[str] = mapped_column(String(200))
    market: Mapped[str | None] = mapped_column(String(10))  # KOSPI / KOSDAQ
    sector: Mapped[str | None] = mapped_column(String(100))


class Financial(Base):
    """분기 재무제표 원천 (writer = dart_adapter). 자연키 (corp_code, year, quarter), AD-7."""

    __tablename__ = "financials"
    __table_args__ = (
        UniqueConstraint("corp_code", "year", "quarter", name="uq_fin_corp_year_q"),
        CheckConstraint("quarter BETWEEN 1 AND 4", name="ck_fin_quarter"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    year: Mapped[int] = mapped_column()
    quarter: Mapped[int] = mapped_column()  # 1~4
    fs_div: Mapped[str | None] = mapped_column(String(3))  # CFS(연결) / OFS(개별)

    # 손익
    revenue: Mapped[int | None] = mapped_column(BigInteger)
    net_income: Mapped[int | None] = mapped_column(BigInteger)
    operating_income: Mapped[int | None] = mapped_column(BigInteger)
    depreciation: Mapped[int | None] = mapped_column(BigInteger)
    # 재무상태
    equity: Mapped[int | None] = mapped_column(BigInteger)
    total_assets: Mapped[int | None] = mapped_column(BigInteger)
    total_liabilities: Mapped[int | None] = mapped_column(BigInteger)
    cash: Mapped[int | None] = mapped_column(BigInteger)
    total_debt: Mapped[int | None] = mapped_column(BigInteger)
    # 환원 (별도 공시 기반, best-effort; 없으면 null)
    dividend_total: Mapped[int | None] = mapped_column(BigInteger)
    buyback_amount: Mapped[int | None] = mapped_column(BigInteger)  # 자사주 매입액
    buyback_retired_amount: Mapped[int | None] = mapped_column(BigInteger)  # 소각액


class Price(Base):
    """일별 시세·시가총액 원천 (writer = krx_adapter). 시총 단일원천(AD-9). 자연키 (corp_code, date)."""

    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint("corp_code", "date", name="uq_prices_corp_date"),
        CheckConstraint(
            "(close IS NULL OR close >= 0) AND (volume IS NULL OR volume >= 0) "
            "AND (trading_value IS NULL OR trading_value >= 0) "
            "AND (market_cap IS NULL OR market_cap >= 0)",
            name="ck_prices_nonneg",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    date: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD (KST)
    close: Mapped[int | None] = mapped_column(BigInteger)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    trading_value: Mapped[int | None] = mapped_column(BigInteger)  # 거래대금
    market_cap: Mapped[int | None] = mapped_column(BigInteger)  # 시가총액(AD-9 단일원천)


class MacroIndicator(Base):
    """매크로 지표 시계열 (writer = ecos_adapter, AD-3). 종목 무관. 자연키 (indicator, date)."""

    __tablename__ = "macro_indicator"
    __table_args__ = (
        UniqueConstraint("indicator", "date", name="uq_macro_indicator_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    indicator: Mapped[str] = mapped_column(String(30), index=True)  # base_rate 등
    date: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD
    value: Mapped[float | None] = mapped_column(Float)
```

### `app/ingest/ecos.py`
```python
"""ECOS(한국은행 경제통계) 소스 어댑터 — macro_indicator의 writer (AD-3).

ECOS StatisticSearch REST API(requests). 지표 카탈로그(통계표·항목·주기) 내장.
fetch(라이브, 키 필요) → normalize(순수) → upsert(멱등, indicator+date).

키는 요청 URL 경로에 포함되므로 예외/로그에 URL을 노출하지 않는다(DART 리뷰 교훈).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.ingest.base import SourceAdapter
from app.repositories.macro import upsert_macro

_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"
_TIMEOUT = (3.05, 20)

# 지표 카탈로그: (indicator, 통계표코드, 항목코드, 주기)  — 라이브 탐침으로 확정
_CATALOG: tuple[tuple[str, str, str, str], ...] = (
    ("base_rate", "722Y001", "0101000", "M"),       # 한국은행 기준금리(월)
    ("bond_3y", "817Y002", "010200000", "D"),        # 국고채(3년)(일)
    ("usd_krw", "731Y001", "0000001", "D"),          # 원/달러 매매기준율(일)
    ("leading_index", "901Y067", "I16E", "M"),       # 경기선행지수순환변동치(월)
)


class EcosAdapterError(RuntimeError):
    """ECOS 어댑터 오류(키 미설정·API 오류·네트워크 실패). 키/URL을 메시지에 넣지 않는다."""


class EcosAdapter(SourceAdapter):
    source = "ecos"

    def __init__(self) -> None:
        self._session = requests.Session()

    def fetch(self, date_from: str, date_to: str) -> dict[str, Any]:
        """카탈로그 4개 지표를 [date_from, date_to](YYYYMMDD)에서 수집.

        반환: {"rows": [{indicator, date, value}]}
        """
        key = settings.ecos_api_key.get_secret_value()
        if not key:
            raise EcosAdapterError(
                "ECOS_API_KEY가 설정되지 않았습니다. .env에 ECOS_API_KEY를 넣으세요."
            )
        rows: list[dict[str, Any]] = []
        for indicator, stat, item, cycle in _CATALOG:
            s = date_from if cycle == "D" else date_from[:6]
            e = date_to if cycle == "D" else date_to[:6]
            ecos_rows = self._get(key, stat, cycle, s, e, item)
            rows.extend(_parse_rows(indicator, ecos_rows))
        return {"rows": rows}

    def _get(
        self, key: str, stat: str, cycle: str, s: str, e: str, item: str
    ) -> list[dict[str, Any]]:
        url = f"{_BASE}/{key}/json/kr/1/1000/{stat}/{cycle}/{s}/{e}/{item}"
        try:
            resp = self._session.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as ex:
            # URL에 키가 포함되므로 예외 메시지에 넣지 않음
            raise EcosAdapterError(
                f"ECOS 요청 실패: stat={stat} ({type(ex).__name__})"
            ) from None
        if "StatisticSearch" in data:
            return data["StatisticSearch"].get("row", [])
        result = data.get("RESULT", {})
        code = result.get("CODE", "")
        if code == "INFO-200":  # 해당 데이터 없음 → 빈 결과(실패 아님)
            return []
        raise EcosAdapterError(f"ECOS API 오류: stat={stat}, code={code}")

    # ── normalize (순수) ──
    def normalize(self, raw: Mapping[str, Any]) -> list[dict[str, Any]]:
        return list(raw.get("rows", []))

    # ── upsert (멱등) ──
    def upsert(self, session: Session, records: Sequence[dict[str, Any]]) -> int:
        for rec in records:
            upsert_macro(session, rec)
        session.flush()
        return len(records)


def _parse_rows(indicator: str, ecos_rows: Sequence[Mapping[str, Any]]) -> list[dict]:
    """ECOS row 목록 → [{indicator, date(ISO), value}]. 순수·테스트가능."""
    out = []
    for r in ecos_rows:
        out.append(
            {
                "indicator": indicator,
                "date": _time_to_iso(str(r.get("TIME", ""))),
                "value": _to_float(r.get("DATA_VALUE")),
            }
        )
    return out


def _time_to_iso(t: str) -> str:
    """ECOS TIME(YYYYMM 월 / YYYYMMDD 일)을 ISO YYYY-MM-DD로(월은 01일)."""
    t = t.strip()
    if len(t) == 6 and t.isdigit():
        return f"{t[:4]}-{t[4:6]}-01"
    if len(t) == 8 and t.isdigit():
        return f"{t[:4]}-{t[4:6]}-{t[6:]}"
    return t


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None
```

### `app/repositories/macro.py`
```python
"""macro_indicator 멱등 upsert (수집 경로 전용). 자연키 (indicator, date), AD-7."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MacroIndicator


def upsert_macro(session: Session, rec: dict) -> MacroIndicator:
    """(indicator, date) 기준 upsert. value None은 기존값을 덮지 않는다."""
    stmt = select(MacroIndicator).where(
        MacroIndicator.indicator == rec["indicator"],
        MacroIndicator.date == rec["date"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = MacroIndicator(indicator=rec["indicator"], date=rec["date"])
        session.add(obj)
    if rec.get("value") is not None:
        obj.value = rec["value"]
    return obj
```

### `app/ingest/run.py`
```python
"""수집 실행 진입점 (간단 함수형; 라우터 POST /ingest/run은 후속 스토리).

트랜잭션 정책(결정): **종목별 커밋 + 실패 목록**. 한 종목의 네트워크/파싱 실패가
이미 성공한 다른 종목의 적재를 되돌리지 않도록 부분 성공을 허용한다.
fetch(네트워크)는 짧은 DB 트랜잭션 밖에서 수행해 DB 커넥션 점유를 최소화한다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.db import SessionLocal
from app.ingest.dart import DartAdapter, DartAdapterError
from app.ingest.ecos import EcosAdapter
from app.ingest.krx import KrxAdapter
from app.models import Company

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    ingested: int = 0
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (corp_code, reason)
    degraded: list[str] = field(default_factory=list)  # 부분성공(예: 시총·거래대금 미수집)


def ingest_financials(
    corp_codes: Sequence[str],
    bsns_year: str,
    reprt_code: str = "11011",
) -> IngestResult:
    """종목별로 fetch→normalize→upsert. 실패는 건너뛰고 목록에 담는다."""
    adapter = DartAdapter()
    result = IngestResult()
    for corp_code in corp_codes:
        try:
            raw = adapter.fetch(corp_code, bsns_year, reprt_code)  # 네트워크(트랜잭션 밖)
            records = adapter.normalize(raw)
            with SessionLocal() as session:  # 종목당 짧은 트랜잭션
                with session.begin():
                    n = adapter.upsert(session, records)
            result.ingested += n
            result.succeeded.append(corp_code)
        except (DartAdapterError, Exception) as e:  # noqa: BLE001 (부분성공 정책)
            logger.warning("수집 실패 corp_code=%s: %s", corp_code, type(e).__name__)
            result.failed.append((corp_code, str(e)))
    return result


def ingest_macro(date_from: str, date_to: str) -> IngestResult:
    """ECOS 매크로 지표(4종)를 [date_from, date_to](YYYYMMDD) 수집·적재."""
    adapter = EcosAdapter()
    result = IngestResult()
    try:
        records = adapter.normalize(adapter.fetch(date_from, date_to))
        with SessionLocal() as session:
            with session.begin():
                result.ingested = adapter.upsert(session, records)
        result.succeeded.append("ecos")
    except Exception as e:  # noqa: BLE001
        logger.warning("매크로 수집 실패: %s", type(e).__name__)
        result.failed.append(("ecos", str(e)))
    return result


def ingest_prices(
    corp_codes: Sequence[str], date_from: str, date_to: str
) -> IngestResult:
    """종목별 시세·시총·거래대금 수집. stock_code는 company에서 조회(AD-5).

    - preflight: company/stock_code 매핑 부재는 먼저 failed로 분리.
    - degraded: 종가는 적재됐으나 시총·거래대금(cap 로그인) 실패 시 corp_code를 degraded에 표시.
    """
    adapter = KrxAdapter()
    result = IngestResult()
    # preflight: stock_code 매핑 확인
    stock_map: dict[str, str] = {}
    with SessionLocal() as session:
        for corp_code in corp_codes:
            company = session.get(Company, corp_code)
            sc = company.stock_code if company else None
            if not sc:
                result.failed.append((corp_code, "company.stock_code 없음(먼저 1.2 수집)"))
            else:
                stock_map[corp_code] = sc

    for corp_code, stock_code in stock_map.items():
        try:
            raw = adapter.fetch(stock_code, corp_code, date_from, date_to)
            records = adapter.normalize(raw)
            with SessionLocal() as session:
                with session.begin():
                    n = adapter.upsert(session, records)
            result.ingested += n
            result.succeeded.append(corp_code)
            if not raw.get("cap_ok"):  # 시총·거래대금 원천 실패 → 부분성공
                logger.warning("시총·거래대금 미수집(degraded) corp_code=%s", corp_code)
                result.degraded.append(corp_code)
        except Exception as e:  # noqa: BLE001 (부분성공 정책)
            logger.warning("시세 수집 실패 corp_code=%s: %s", corp_code, type(e).__name__)
            result.failed.append((corp_code, str(e)))
    return result
```

### `alembic/versions/0004_macro.py`
```python
"""macro_indicator table

Revision ID: 0004_macro
Revises: 0003_prices
Create Date: 2026-07-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_macro"
down_revision: str | None = "0003_prices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "macro_indicator",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("indicator", sa.String(length=30), nullable=False, index=True),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("value", sa.Float),
        sa.UniqueConstraint("indicator", "date", name="uq_macro_indicator_date"),
    )


def downgrade() -> None:
    op.drop_table("macro_indicator")
```

### `tests/test_ecos_ingest.py`
```python
"""Story 1.4 — ECOS 어댑터 정규화·멱등 upsert 검증 (라이브 키 없이 fixture)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.ingest.ecos import EcosAdapter, EcosAdapterError, _parse_rows, _time_to_iso
from app.models import Base, MacroIndicator


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


# 가짜 ECOS row (월/일 섞임)
_FAKE_ROWS = [
    {"TIME": "202401", "DATA_VALUE": "3.5", "ITEM_NAME1": "기준금리"},
    {"TIME": "202402", "DATA_VALUE": "3.5"},
]


def test_time_to_iso() -> None:
    assert _time_to_iso("202401") == "2024-01-01"       # 월 → 01일
    assert _time_to_iso("20240102") == "2024-01-02"     # 일
    assert _time_to_iso("") == ""


def test_parse_rows_maps() -> None:
    recs = _parse_rows("base_rate", _FAKE_ROWS)
    assert recs[0] == {"indicator": "base_rate", "date": "2024-01-01", "value": 3.5}
    assert len(recs) == 2


def test_parse_rows_handles_missing_value() -> None:
    recs = _parse_rows("bond_3y", [{"TIME": "20240102", "DATA_VALUE": "-"}])
    assert recs[0]["value"] is None


def test_upsert_is_idempotent(session: Session) -> None:
    """AC4: (indicator, date) 멱등 — 2회 실행해도 중복 없음."""
    adapter = EcosAdapter()
    recs = _parse_rows("base_rate", _FAKE_ROWS)
    adapter.upsert(session, recs)
    session.commit()
    adapter.upsert(session, recs)
    session.commit()
    n = session.scalar(select(func.count()).select_from(MacroIndicator))
    assert n == 2


def test_fetch_without_key_raises(monkeypatch) -> None:
    """AC5: ECOS_API_KEY 미설정 시 명확한 에러."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "ecos_api_key", SecretStr(""))
    with pytest.raises(EcosAdapterError, match="ECOS_API_KEY"):
        EcosAdapter().fetch("20240101", "20240301")
```

## 이미 알려진 것 (중복 지적 불필요)
- 지표 통계코드/항목/주기는 라이브 탐침으로 확정(base_rate M, bond_3y D, usd_krw D, leading_index M).
- 키가 URL 경로에 들어가 예외에 URL 미노출 처리함(의도).
- 라이브 128건 수집 검증됨(pytest 33 passed).
- SourceAdapter/IngestResult/None안덮음/config SecretStr은 이전 스토리에서 확립·리뷰됨.

## 출력 형식
[High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정
