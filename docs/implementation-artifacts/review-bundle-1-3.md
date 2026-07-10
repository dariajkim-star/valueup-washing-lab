# 코드 리뷰 요청 — 밸류업 워싱 스크리너 Story 1.3 (시세·시총·거래대금 수집, KRX)

너는 엄격한(adversarial) 시니어 코드 리뷰어야. 아래 스토리/AC, 아키텍처 제약, 코드를 보고
버그·규약 위반·엣지케이스·테스트 허점을 찾아줘. [High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정 형태로. 칭찬 생략, 없으면 "clean".

**이번 스토리 핵심 = 외부 로그인 API + 두 소스 병합**이라 특히:
- KRX 로그인 세션 관리(pykrx가 os.environ로 자격증명 읽음), 계정 잠금(loginErrCnt) 위험, 세션 만료/재로그인
- os.environ에 KRX_ID/KRX_PW 주입하는 방식의 부작용(다른 코드·테스트에 전역 오염, 시크릿 노출)
- get_market_ohlcv(종가·거래량) + get_market_cap(시총·거래대금) 두 DataFrame 병합의 엣지케이스(날짜 불일치, 결측일, 상장폐지, 정지)
- 멱등 upsert, stock_code↔corp_code 매핑 실패
- pykrx 예외/빈 응답(로그인 실패 시 조용히 cap=None)

## 스토리 & AC
- As a 애널리스트, KRX에서 종가·거래량·거래대금·시가총액이 prices에 적재된다.
- AC1: prices 테이블(마이그레이션 0003), 자연키 (corp_code, date), corp_code(8자리) FK
- AC2: krx_adapter(fetch→normalize→upsert, AD-3)로 prices 적재
- AC3: pykrx는 stock_code(6자리) 조회, 저장은 corp_code(8자리) — company에서 매핑(AD-5)
- AC4: 시가총액 단일원천=prices(AD-9), company에 없음
- AC5: (corp_code, date) 멱등 upsert
- AC6: KRX_ID/KRX_PW 미설정 시 명확한 에러
- AC7: fixture로 정규화·멱등 단위테스트(계정 없이 CI)

## 아키텍처 제약
- AD-2 레이어 단방향(수집은 서빙과 분리), AD-3 어댑터=prices 유일 writer/공통 인터페이스,
- AD-5 corp_code 정식키, AD-7 멱등 upsert, AD-9 시총 단일원천=prices, NFR2 결측 null 허용.

## 변경 코드

### `app/config.py`
```python
"""애플리케이션 설정 (pydantic-settings).

임계치·가중치는 절대 코드에 하드코딩하지 않는다(NFR3, AD-4/AD-10).
gap_engine·mna_engine 등 후속 스토리가 여기서 값을 읽는다.

시크릿(API 키·DB URL)은 SecretStr로 감싸 로그·에러·model_dump에 원문이 노출되지 않게 한다.
.env 경로는 실행 위치(cwd)에 의존하지 않도록 프로젝트 루트로 고정한다.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 프로젝트 루트(app/의 부모) 기준 .env — pytest·alembic·uvicorn 어디서 실행해도 동일
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,  # 검증 에러에 입력값(시크릿) 노출 방지
    )

    # ── 앱 ──
    app_name: str = "밸류업 워싱 스크리너"
    debug: bool = False

    # ── DB ── (PostgreSQL 기본, 로컬 개발은 SQLite 폴백). URL에 비밀번호 포함 가능 → SecretStr
    database_url: SecretStr = SecretStr("sqlite:///./valueup.db")

    # ── 외부 소스 API 키 (소스 3종: DART · KRX · ECOS) ──
    # v1 스캐폴딩은 빈 기본값 허용(부팅 가능). 실제 필수화는 수집 스토리(1.2~)에서.
    dart_api_key: SecretStr = SecretStr("")
    ecos_api_key: SecretStr = SecretStr("")
    # KRX는 시가총액·거래대금 조회에 로그인 필요(pykrx가 KRX_ID/KRX_PW 환경변수 사용)
    krx_id: SecretStr = SecretStr("")
    krx_pw: SecretStr = SecretStr("")

    # ── 워싱 판정 임계치 (scoring.md), 0~1 범위 ──
    washing_progress_min: float = Field(0.5, ge=0.0, le=1.0)
    washing_achievement_max: float = Field(0.6, ge=0.0, le=1.0)

    # ── Value-up 실행점수 가중치 (합 1.0) ──
    score_w_achievement: float = Field(0.5, ge=0.0, le=1.0)
    score_w_buyback: float = Field(0.3, ge=0.0, le=1.0)
    score_w_payout: float = Field(0.2, ge=0.0, le=1.0)

    # ── M&A Target Score 가중치 (합 1.0) ──
    mna_w_valuation: float = Field(0.35, ge=0.0, le=1.0)
    mna_w_capacity: float = Field(0.25, ge=0.0, le=1.0)
    mna_w_ownership: float = Field(0.25, ge=0.0, le=1.0)
    mna_w_macro: float = Field(0.15, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_weight_sums(self) -> "Settings":
        """가중치 그룹 합이 1.0인지 검증(오설정 조기 발견)."""
        vu = self.score_w_achievement + self.score_w_buyback + self.score_w_payout
        mna = (
            self.mna_w_valuation
            + self.mna_w_capacity
            + self.mna_w_ownership
            + self.mna_w_macro
        )
        if abs(vu - 1.0) > 1e-6:
            raise ValueError(f"Value-up 가중치 합이 1.0이 아님: {vu}")
        if abs(mna - 1.0) > 1e-6:
            raise ValueError(f"M&A 가중치 합이 1.0이 아님: {mna}")
        return self


settings = Settings()
```

### `app/models.py`
```python
"""SQLAlchemy ORM 모델.

엔티티 정식 키는 corp_code(8자리)다(AD-5). stock_code(6자리)는 company 속성.
시가총액은 company에 두지 않는다(AD-9, 시총 단일원천=prices/KRX, Story 1.3).

Story 1.2: Company, Financial 추가.
후속: prices / valueup_plan / ownership / macro_indicator / valueup_score / mna_score.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, UniqueConstraint
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
```

### `app/ingest/krx.py`
```python
"""KRX 소스 어댑터 — prices의 writer (AD-3). 시가총액 단일원천(AD-9).

pykrx `get_market_cap(from,to,ticker)`는 종가·시가총액·거래량·거래대금을 한 번에 준다
(시총·거래대금 조회는 KRX 로그인 필요 → KRX_ID/KRX_PW를 os.environ에 주입).
ticker=stock_code(6자리)로 조회, 저장 키는 corp_code(8자리)(AD-5).

fetch(라이브, 로그인 필요) → normalize(순수) → upsert(멱등, corp_code+date).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.ingest.base import SourceAdapter
from app.repositories.prices import upsert_price

# 컬럼 매핑 (두 소스 병합)
#   get_market_ohlcv(로그인 불필요): 종가·거래량
#   get_market_cap  (로그인 필요)  : 시가총액·거래대금
_OHLCV_MAP = {"종가": "close", "거래량": "volume"}
_CAP_MAP = {"시가총액": "market_cap", "거래대금": "trading_value"}


class KrxAdapterError(RuntimeError):
    """KRX 어댑터 오류(로그인 미설정 등)."""


class KrxAdapter(SourceAdapter):
    source = "krx"

    def fetch(
        self, stock_code: str, corp_code: str, date_from: str, date_to: str
    ) -> dict[str, Any]:
        """pykrx로 [date_from, date_to] 시세·시총·거래대금 수집. 날짜는 YYYYMMDD."""
        krx_id = settings.krx_id.get_secret_value()
        krx_pw = settings.krx_pw.get_secret_value()
        if not (krx_id and krx_pw):
            raise KrxAdapterError(
                "KRX_ID/KRX_PW가 설정되지 않았습니다(시총·거래대금 조회에 필요). "
                ".env에 KRX_ID, KRX_PW를 넣으세요."
            )
        # pykrx는 환경변수에서 자격증명을 읽는다
        os.environ["KRX_ID"] = krx_id
        os.environ["KRX_PW"] = krx_pw
        try:
            from pykrx import stock  # noqa: PLC0415  (지연 import)
        except ImportError as e:  # pragma: no cover
            raise KrxAdapterError("pykrx가 설치되지 않았습니다.") from e

        # 종가·거래량 (로그인 불필요, 안정)
        ohlcv = stock.get_market_ohlcv(date_from, date_to, stock_code)
        # 시가총액·거래대금 (로그인 필요). 일시 실패해도 종가는 남기도록 관대 처리.
        try:
            cap = stock.get_market_cap(date_from, date_to, stock_code)
        except Exception:  # noqa: BLE001
            cap = None
        return {
            "corp_code": corp_code,
            "rows": _merge_frames(ohlcv, cap),
        }

    def normalize(self, raw: Mapping[str, Any]) -> list[dict[str, Any]]:
        """intermediate rows에 corp_code를 붙여 price 레코드로."""
        corp_code = raw["corp_code"]
        return [{"corp_code": corp_code, **row} for row in raw.get("rows", [])]

    def upsert(
        self, session: Session, records: Sequence[dict[str, Any]]
    ) -> int:
        for rec in records:
            upsert_price(session, rec)
        session.flush()
        return len(records)


def _merge_frames(ohlcv: Any, cap: Any) -> list[dict[str, Any]]:
    """ohlcv(종가·거래량)와 cap(시총·거래대금) DataFrame을 날짜로 병합.

    순수 함수(테스트 가능). cap이 None이면 시총·거래대금은 null.
    """
    by_date: dict[str, dict[str, Any]] = {}
    _fill(by_date, ohlcv, _OHLCV_MAP)
    if cap is not None:
        _fill(by_date, cap, _CAP_MAP)
    # 모든 필드 키를 채우고 date 순으로 반환
    rows = []
    for date in sorted(by_date):
        row = {"date": date, "close": None, "volume": None,
               "trading_value": None, "market_cap": None}
        row.update(by_date[date])
        rows.append(row)
    return rows


def _fill(acc: dict, df: Any, colmap: dict[str, str]) -> None:
    if df is None:
        return
    for idx, series in df.iterrows():
        date_iso = _to_iso(idx)
        bucket = acc.setdefault(date_iso, {"date": date_iso})
        for kcol, field in colmap.items():
            if kcol in series.index:
                bucket[field] = _to_int(series[kcol])


def _to_iso(idx: Any) -> str:
    """Timestamp/문자열 인덱스를 YYYY-MM-DD로."""
    if hasattr(idx, "strftime"):
        return idx.strftime("%Y-%m-%d")
    s = str(idx)
    # '20240102' → '2024-01-02'
    digits = s.replace("-", "")
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return s


def _to_int(v: Any) -> int | None:
    try:
        if v is None:
            return None
        return int(v)
    except (TypeError, ValueError):
        return None
```

### `app/repositories/prices.py`
```python
"""prices 멱등 upsert 저장소 (수집 경로 전용). 자연키 (corp_code, date), AD-7."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Price


def upsert_price(session: Session, rec: dict) -> Price:
    """(corp_code, date) 기준 price upsert. None 값은 기존값을 덮지 않는다."""
    stmt = select(Price).where(
        Price.corp_code == rec["corp_code"], Price.date == rec["date"]
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = Price(corp_code=rec["corp_code"], date=rec["date"])
        session.add(obj)
    for field in ("close", "volume", "trading_value", "market_cap"):
        if rec.get(field) is not None:
            setattr(obj, field, rec[field])
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
from app.ingest.krx import KrxAdapter
from app.models import Company

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    ingested: int = 0
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (corp_code, reason)


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


def ingest_prices(
    corp_codes: Sequence[str], date_from: str, date_to: str
) -> IngestResult:
    """종목별 시세·시총·거래대금 수집. stock_code는 company에서 조회(AD-5)."""
    adapter = KrxAdapter()
    result = IngestResult()
    for corp_code in corp_codes:
        try:
            with SessionLocal() as session:
                company = session.get(Company, corp_code)
                stock_code = company.stock_code if company else None
            if not stock_code:
                raise ValueError(f"company.stock_code 없음: {corp_code} (먼저 1.2 수집)")
            raw = adapter.fetch(stock_code, corp_code, date_from, date_to)
            records = adapter.normalize(raw)
            with SessionLocal() as session:
                with session.begin():
                    n = adapter.upsert(session, records)
            result.ingested += n
            result.succeeded.append(corp_code)
        except Exception as e:  # noqa: BLE001 (부분성공 정책)
            logger.warning("시세 수집 실패 corp_code=%s: %s", corp_code, type(e).__name__)
            result.failed.append((corp_code, str(e)))
    return result
```

### `alembic/versions/0003_prices.py`
```python
"""prices table

Revision ID: 0003_prices
Revises: 0002_company_financials
Create Date: 2026-07-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_prices"
down_revision: str | None = "0002_company_financials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prices",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "corp_code",
            sa.String(length=8),
            sa.ForeignKey("company.corp_code"),
            nullable=False,
            index=True,
        ),
        sa.Column("date", sa.String(length=10), nullable=False),
        sa.Column("close", sa.BigInteger),
        sa.Column("volume", sa.BigInteger),
        sa.Column("trading_value", sa.BigInteger),
        sa.Column("market_cap", sa.BigInteger),
        sa.UniqueConstraint("corp_code", "date", name="uq_prices_corp_date"),
    )


def downgrade() -> None:
    op.drop_table("prices")
```

### `tests/test_krx_ingest.py`
```python
"""Story 1.3 — KRX 어댑터 정규화·멱등 upsert 검증 (라이브 계정 없이 fixture)."""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.ingest.krx import KrxAdapter, KrxAdapterError, _merge_frames
from app.models import Base, Company, Price


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        # prices.corp_code FK 충족을 위한 company
        s.add(Company(corp_code="00126380", stock_code="005930", corp_name="삼성전자"))
        s.commit()
        yield s


def _fake_ohlcv_df() -> pd.DataFrame:
    """pykrx get_market_ohlcv 형태(종가·거래량 포함)."""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    return pd.DataFrame(
        {"시가": [78200, 78500], "고가": [79800, 78800], "저가": [78200, 77000],
         "종가": [79600, 77000], "거래량": [17_142_847, 21_753_644], "등락률": [1, -3]},
        index=idx,
    )


def _fake_cap_df() -> pd.DataFrame:
    """pykrx get_market_cap 형태(시총·거래대금, 종가 없음)."""
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    return pd.DataFrame(
        {"시가총액": [475_000_000_000_000, 459_000_000_000_000],
         "거래량": [17_142_847, 21_753_644],
         "거래대금": [1_360_000_000_000, 1_680_000_000_000],
         "상장주식수": [5969782550, 5969782550]},
        index=idx,
    )


def test_merge_frames_maps_and_formats() -> None:
    """두 소스 병합: 종가(ohlcv) + 시총·거래대금(cap), ISO 날짜, 정수."""
    rows = _merge_frames(_fake_ohlcv_df(), _fake_cap_df())
    assert rows[0] == {
        "date": "2024-01-02",
        "close": 79600,
        "volume": 17_142_847,
        "trading_value": 1_360_000_000_000,
        "market_cap": 475_000_000_000_000,
    }
    assert len(rows) == 2


def test_merge_frames_cap_none_keeps_close() -> None:
    """cap이 None(로그인 실패)이어도 종가·거래량은 남고 시총은 null."""
    rows = _merge_frames(_fake_ohlcv_df(), None)
    assert rows[0]["close"] == 79600
    assert rows[0]["market_cap"] is None


def test_normalize_attaches_corp_code() -> None:
    raw = {"corp_code": "00126380",
           "rows": _merge_frames(_fake_ohlcv_df(), _fake_cap_df())}
    recs = KrxAdapter().normalize(raw)
    assert all(r["corp_code"] == "00126380" for r in recs)
    assert recs[0]["market_cap"] == 475_000_000_000_000


def test_upsert_is_idempotent(session: Session) -> None:
    """AC5: (corp_code, date) 멱등 — 2회 실행해도 중복 없음."""
    adapter = KrxAdapter()
    recs = adapter.normalize(
        {"corp_code": "00126380",
         "rows": _merge_frames(_fake_ohlcv_df(), _fake_cap_df())}
    )
    adapter.upsert(session, recs)
    session.commit()
    adapter.upsert(session, recs)
    session.commit()
    count = session.scalar(select(func.count()).select_from(Price))
    assert count == 2  # 2일치, 중복 없음


def test_fetch_without_credentials_raises(monkeypatch) -> None:
    """AC6: KRX_ID/KRX_PW 미설정 시 명확한 에러."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "krx_id", SecretStr(""))
    monkeypatch.setattr(settings, "krx_pw", SecretStr(""))
    with pytest.raises(KrxAdapterError, match="KRX_ID"):
        KrxAdapter().fetch("005930", "00126380", "20240101", "20240105")
```

## 이미 알려진 것 (중복 지적 불필요)
- pykrx get_market_cap은 종가를 안 줘서 get_market_ohlcv와 병합함(의도된 설계).
- KRX 로그인은 카카오연동/CD006/CD011 트러블슈팅 거쳐 성공, 계정잠금 위험은 인지함.
- 라이브 검증됨: 삼성·하이닉스 실데이터 수집(pytest 24 passed).
- SourceAdapter/IngestResult/None안덮음 패턴은 Story 1.2에서 확립.
- config의 SecretStr·validator·.env 루트고정은 Story 1.1에서 리뷰 완료.

## 출력 형식
[High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정
