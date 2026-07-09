# 코드 리뷰 요청 — 밸류업 워싱 스크리너 Story 1.2 (재무 수집, DART)

너는 엄격한(adversarial) 시니어 코드 리뷰어야. 아래 스토리/AC, 아키텍처 제약, 코드를 보고
버그·규약 위반·엣지케이스·테스트 허점을 찾아줘. 각 발견은 [High/Med/Low] 파일:라인 — 문제 — 근거/재현조건 — 제안수정 형태로.
칭찬 생략, 문제만. 없으면 "clean".

**이번 스토리 핵심 = 외부 API 연동**이라 특히 아래를 집중적으로 봐줘:
- OpenDART REST 호출의 에러/타임아웃/재시도/rate-limit(분당 100) 처리
- 금액 파싱·계정명 매핑의 엣지케이스(음수, 억단위 표기, 중복 계정명, CFS/OFS 폴백)
- 멱등 upsert의 동시성/트랜잭션 경계
- SecretStr 키가 로그·예외·요청에 노출되는지
- 네트워크 실패 시 부분 적재/롤백 처리

## 스토리 & AC
- As a 애널리스트, DART에서 기본정보+분기 재무제표가 DB에 적재된다.
- AC1: company·financials 테이블(마이그레이션 0002), corp_code(8자리) 키, financials 자연키 (corp_code, year, quarter)
- AC2: dart_adapter(fetch→normalize→upsert, AD-3)로 company·financials 적재
- AC3: 재실행 시 (corp_code,year,quarter) 멱등 upsert — 중복 없음
- AC4: 계정 못 찾으면 null, 수집 실패 안 함
- AC5: DART_API_KEY 미설정 시 명확한 에러
- AC6: fixture로 정규화·upsert 단위테스트(라이브 키 없이 CI)

## 아키텍처 제약
- AD-2: 레이어 단방향(routers→services→repositories→models/DB). 수집은 서빙과 분리.
- AD-3: 원천테이블 writer=어댑터 하나. 공통 인터페이스 fetch→normalize→upsert.
- AD-5: corp_code(8자리) 정식 키, stock_code(6자리)는 속성.
- AD-7: 자연키 멱등 upsert.
- AD-9: company에 market_cap 없음(시총=prices/KRX).
- NFR2: 계정 null 허용, 0 나눗셈 방어.

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

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """모든 ORM 모델의 공통 Base."""

    pass


class Company(Base):
    """상장사 기본정보 (writer = dart_adapter, AD-3/AD-9)."""

    __tablename__ = "company"

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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    year: Mapped[int] = mapped_column()
    quarter: Mapped[int] = mapped_column()  # 1~4

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
```

### `app/ingest/base.py`
```python
"""소스 어댑터 공통 인터페이스 (AD-3).

각 원천 소스(dart/krx/ecos)는 이 인터페이스를 구현하며,
자기가 맡은 원천 테이블의 유일한 writer다. 파이프-필터: fetch → normalize → upsert.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.orm import Session


class SourceAdapter(ABC):
    """수집 어댑터 베이스. fetch(원천 호출) → normalize(정규화) → upsert(멱등 적재)."""

    #: 소스 식별자 (dart / krx / ecos)
    source: str = ""

    @abstractmethod
    def fetch(self, *args: Any, **kwargs: Any) -> Any:
        """외부 소스에서 원시 데이터를 가져온다(네트워크·키 필요)."""

    @abstractmethod
    def normalize(self, raw: Any) -> Any:
        """원시 데이터를 DB 적재용 레코드로 정규화한다(순수 로직, 테스트 가능)."""

    @abstractmethod
    def upsert(self, session: Session, records: Any) -> int:
        """정규화 레코드를 자연키 기준 멱등 upsert한다(AD-7). 적재 행 수 반환."""
```

### `app/ingest/dart.py`
```python
"""DART(전자공시) 소스 어댑터 — company·financials의 writer (AD-3).

OpenDART REST API(requests)를 사용한다:
  - company.json          : 기업개황(회사명·종목코드·시장구분·업종)
  - fnlttSinglAcntAll.json : 단일회사 전체 재무제표(계정명→금액)
dart-fss의 XBRL 추출보다 빠르고 견고하며, normalize(계정→컬럼)에 바로 맞는다.

fetch: REST 호출(키 필요). normalize: 계정명 매핑(순수, 테스트 가능). upsert: 멱등 적재.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.ingest.base import SourceAdapter
from app.repositories.financials import upsert_company, upsert_financial

_BASE = "https://opendart.fss.or.kr/api"

# corp_cls → 시장 구분
_MARKET = {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX", "E": "기타"}

# reprt_code(보고서) → quarter
_REPRT_QUARTER = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}

# 재무 컬럼 → 후보 계정명(라벨). 앞에서부터 매칭, 없으면 null(NFR2).
_ACCOUNT_MAP: dict[str, tuple[str, ...]] = {
    "revenue": ("매출액", "수익(매출액)", "영업수익"),
    "net_income": ("당기순이익", "당기순이익(손실)", "분기순이익"),
    "operating_income": ("영업이익", "영업이익(손실)"),
    "depreciation": ("감가상각비",),
    "equity": ("자본총계",),
    "total_assets": ("자산총계",),
    "total_liabilities": ("부채총계",),
    "cash": ("현금및현금성자산",),
    "total_debt": ("단기차입금", "장기차입금", "사채"),
}


class DartAdapterError(RuntimeError):
    """DART 어댑터 오류(키 미설정·API 오류 등)."""


class DartAdapter(SourceAdapter):
    source = "dart"

    # ── fetch (라이브, 키 필요) ──
    def fetch(
        self,
        corp_code: str,
        bsns_year: str,
        reprt_code: str = "11011",
        fs_div: str = "CFS",
    ) -> dict[str, Any]:
        """OpenDART REST로 기업개황 + 재무제표를 수집해 intermediate 구조로 반환.

        반환: {"company": {...}, "periods": [{"year","quarter","accounts": {label: value}}]}
        연결(CFS)이 비면 개별(OFS)로 폴백한다.
        """
        key = settings.dart_api_key.get_secret_value()
        if not key:
            raise DartAdapterError(
                "DART_API_KEY가 설정되지 않았습니다. .env에 DART_API_KEY를 넣으세요."
            )

        company = self._fetch_company(key, corp_code)
        accounts = self._fetch_accounts(key, corp_code, bsns_year, reprt_code, fs_div)
        period = {
            "year": int(bsns_year),
            "quarter": _REPRT_QUARTER.get(reprt_code, 4),
            "accounts": accounts,
        }
        return {"company": company, "periods": [period]}

    def _fetch_company(self, key: str, corp_code: str) -> dict[str, Any]:
        data = self._get("company.json", {"crtfc_key": key, "corp_code": corp_code})
        return {
            "corp_code": corp_code,
            "stock_code": data.get("stock_code") or None,
            "corp_name": data.get("corp_name", ""),
            "market": _MARKET.get(data.get("corp_cls", ""), None),
            "sector": data.get("induty_code") or None,
        }

    def _fetch_accounts(
        self, key: str, corp_code: str, bsns_year: str, reprt_code: str, fs_div: str
    ) -> dict[str, int]:
        params = {
            "crtfc_key": key,
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        }
        data = self._get("fnlttSinglAcntAll.json", params, allow_no_data=True)
        rows = data.get("list") or []
        if not rows and fs_div == "CFS":
            # 연결이 없으면 개별(OFS) 폴백
            params["fs_div"] = "OFS"
            data = self._get("fnlttSinglAcntAll.json", params, allow_no_data=True)
            rows = data.get("list") or []
        accounts: dict[str, int] = {}
        for row in rows:
            name = row.get("account_nm", "")
            val = _parse_amount(row.get("thstrm_amount"))
            # 같은 계정명이 여러 재무제표에 나오면 첫 값 유지
            if val is not None and name not in accounts:
                accounts[name] = val
        return accounts

    def _get(
        self, endpoint: str, params: Mapping[str, Any], allow_no_data: bool = False
    ) -> dict[str, Any]:
        resp = requests.get(f"{_BASE}/{endpoint}", params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")
        if status == "000":
            return data
        # 013 = 조회된 데이터 없음 (재무제표 폴백에서 허용)
        if allow_no_data and status == "013":
            return {"list": []}
        raise DartAdapterError(
            f"DART API 오류({endpoint}): status={status}, msg={data.get('message')}"
        )

    # ── normalize (순수, 테스트 가능) ──
    def normalize(
        self, raw: Mapping[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        company = dict(raw["company"])
        corp_code = company["corp_code"]
        fin_recs: list[dict[str, Any]] = []
        for period in raw.get("periods", []):
            accounts: Mapping[str, Any] = period.get("accounts", {})
            rec: dict[str, Any] = {
                "corp_code": corp_code,
                "year": period["year"],
                "quarter": period["quarter"],
            }
            for col, labels in _ACCOUNT_MAP.items():
                rec[col] = _pick(accounts, labels)
            # 환원 항목은 전체 재무제표에 없음 → best-effort(있으면 사용, 없으면 null)
            rec["dividend_total"] = period.get("dividend_total")
            rec["buyback_amount"] = period.get("buyback_amount")
            rec["buyback_retired_amount"] = period.get("buyback_retired_amount")
            fin_recs.append(rec)
        return company, fin_recs

    # ── upsert (멱등) ──
    def upsert(
        self, session: Session, records: tuple[dict[str, Any], Sequence[dict[str, Any]]]
    ) -> int:
        company_rec, fin_recs = records
        upsert_company(session, company_rec)
        for rec in fin_recs:
            upsert_financial(session, rec)
        session.flush()
        return len(fin_recs)


def _parse_amount(raw: Any) -> int | None:
    """DART 금액 문자열('514,531,948,000,000')을 정수로. 빈값/'-'는 None(NFR2)."""
    if raw is None:
        return None
    s = str(raw).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _pick(accounts: Mapping[str, Any], labels: tuple[str, ...]) -> int | None:
    """후보 라벨 중 처음 매칭되는 값을 정수로 반환. 없으면 None(NFR2)."""
    for label in labels:
        if label in accounts and accounts[label] is not None:
            try:
                return int(accounts[label])
            except (TypeError, ValueError):
                return None
    return None
```

### `app/ingest/run.py`
```python
"""수집 실행 진입점 (간단 함수형; 라우터 POST /ingest/run은 후속 스토리)."""

from __future__ import annotations

from collections.abc import Sequence

from app.db import SessionLocal
from app.ingest.dart import DartAdapter


def ingest_financials(
    corp_codes: Sequence[str],
    bsns_year: str,
    reprt_code: str = "11011",
) -> int:
    """주어진 종목들의 재무제표를 DART에서 수집·적재. 적재된 재무 행 수 반환."""
    adapter = DartAdapter()
    total = 0
    with SessionLocal() as session:
        for corp_code in corp_codes:
            raw = adapter.fetch(corp_code, bsns_year, reprt_code)
            records = adapter.normalize(raw)
            total += adapter.upsert(session, records)
        session.commit()
    return total
```

### `app/repositories/financials.py`
```python
"""company / financials 멱등 upsert 저장소.

수집 경로 전용(서빙 아님). 자연키 기준으로 존재하면 갱신, 없으면 삽입 → 재실행 안전(AD-7).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Financial


def upsert_company(session: Session, rec: dict) -> Company:
    """corp_code 기준 company upsert."""
    obj = session.get(Company, rec["corp_code"])
    if obj is None:
        obj = Company(corp_code=rec["corp_code"])
        session.add(obj)
    obj.stock_code = rec.get("stock_code")
    obj.corp_name = rec.get("corp_name", obj.corp_name or "")
    obj.market = rec.get("market")
    obj.sector = rec.get("sector")
    return obj


def upsert_financial(session: Session, rec: dict) -> Financial:
    """(corp_code, year, quarter) 자연키 기준 financials upsert."""
    stmt = select(Financial).where(
        Financial.corp_code == rec["corp_code"],
        Financial.year == rec["year"],
        Financial.quarter == rec["quarter"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = Financial(
            corp_code=rec["corp_code"], year=rec["year"], quarter=rec["quarter"]
        )
        session.add(obj)
    # 값 필드만 갱신(자연키 제외). 없으면 null 유지(NFR2).
    for field in (
        "revenue", "net_income", "operating_income", "depreciation",
        "equity", "total_assets", "total_liabilities", "cash", "total_debt",
        "dividend_total", "buyback_amount", "buyback_retired_amount",
    ):
        if field in rec:
            setattr(obj, field, rec[field])
    return obj
```

### `alembic/versions/0002_company_financials.py`
```python
"""company + financials tables

Revision ID: 0002_company_financials
Revises: 0001_baseline
Create Date: 2026-07-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_company_financials"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "company",
        sa.Column("corp_code", sa.String(length=8), primary_key=True),
        sa.Column("stock_code", sa.String(length=6), index=True),
        sa.Column("corp_name", sa.String(length=200), nullable=False),
        sa.Column("market", sa.String(length=10)),
        sa.Column("sector", sa.String(length=100)),
    )
    op.create_table(
        "financials",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "corp_code",
            sa.String(length=8),
            sa.ForeignKey("company.corp_code"),
            nullable=False,
            index=True,
        ),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("quarter", sa.Integer, nullable=False),
        sa.Column("revenue", sa.BigInteger),
        sa.Column("net_income", sa.BigInteger),
        sa.Column("operating_income", sa.BigInteger),
        sa.Column("depreciation", sa.BigInteger),
        sa.Column("equity", sa.BigInteger),
        sa.Column("total_assets", sa.BigInteger),
        sa.Column("total_liabilities", sa.BigInteger),
        sa.Column("cash", sa.BigInteger),
        sa.Column("total_debt", sa.BigInteger),
        sa.Column("dividend_total", sa.BigInteger),
        sa.Column("buyback_amount", sa.BigInteger),
        sa.Column("buyback_retired_amount", sa.BigInteger),
        sa.UniqueConstraint(
            "corp_code", "year", "quarter", name="uq_fin_corp_year_q"
        ),
    )


def downgrade() -> None:
    op.drop_table("financials")
    op.drop_table("company")
```

### `tests/fixtures/__init__.py`
```python
"""테스트 fixture — 가짜 DART 응답(라이브 키 없이 정규화·upsert 검증)."""

from __future__ import annotations

from typing import Any

# 가짜 DART intermediate: 삼성전자 예시(계정명 일부만, 일부 누락으로 null 검증)
DART_RAW_SAMSUNG: dict[str, Any] = {
    "company": {
        "corp_code": "00126380",
        "stock_code": "005930",
        "corp_name": "삼성전자",
        "market": "KOSPI",
        "sector": "반도체",
    },
    "periods": [
        {
            "year": 2026,
            "quarter": 1,
            "accounts": {
                "매출액": 70_000_000_000_000,
                "당기순이익": 8_000_000_000_000,
                "영업이익": 9_000_000_000_000,
                "자본총계": 300_000_000_000_000,
                "자산총계": 450_000_000_000_000,
                "부채총계": 150_000_000_000_000,
                "현금및현금성자산": 40_000_000_000_000,
                # depreciation·차입금 누락 → null 검증
            },
            "dividend_total": 2_000_000_000_000,
            # buyback 항목 누락 → null
        }
    ],
}
```

### `tests/test_dart_ingest.py`
```python
"""Story 1.2 — DART 어댑터 정규화·멱등 upsert 검증 (라이브 키 없이 fixture)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.ingest.dart import DartAdapter, DartAdapterError
from app.models import Base, Financial
from tests.fixtures import DART_RAW_SAMSUNG


def settings_has_key() -> bool:
    return bool(settings.dart_api_key.get_secret_value())


@pytest.fixture()
def session() -> Session:
    """인메모리 SQLite 세션(외부 DB 불필요)."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_normalize_maps_accounts() -> None:
    """AC2/AC4: 계정명이 컬럼으로 매핑되고, 누락 계정은 null."""
    company, fins = DartAdapter().normalize(DART_RAW_SAMSUNG)
    assert company["corp_code"] == "00126380"
    assert company["market"] == "KOSPI"
    assert len(fins) == 1
    rec = fins[0]
    assert rec["revenue"] == 70_000_000_000_000
    assert rec["net_income"] == 8_000_000_000_000
    assert rec["equity"] == 300_000_000_000_000
    # 누락 계정 → null (NFR2)
    assert rec["depreciation"] is None
    assert rec["total_debt"] is None
    assert rec["buyback_amount"] is None
    assert rec["buyback_retired_amount"] is None
    assert rec["dividend_total"] == 2_000_000_000_000


def test_upsert_is_idempotent(session: Session) -> None:
    """AC3: 같은 배치 2회 실행해도 (corp_code,year,quarter) 중복 행 없음."""
    adapter = DartAdapter()
    records = adapter.normalize(DART_RAW_SAMSUNG)

    adapter.upsert(session, records)
    session.commit()
    adapter.upsert(session, records)  # 재실행
    session.commit()

    count = session.scalar(select(func.count()).select_from(Financial))
    assert count == 1  # 중복 없음


def test_upsert_updates_values(session: Session) -> None:
    """AC3: 재실행 시 값이 갱신된다(새 행 추가 아님)."""
    adapter = DartAdapter()
    company, fins = adapter.normalize(DART_RAW_SAMSUNG)
    adapter.upsert(session, (company, fins))
    session.commit()

    fins[0]["net_income"] = 9_999_999_999_999  # 값 변경 후 재적재
    adapter.upsert(session, (company, fins))
    session.commit()

    obj = session.scalars(select(Financial)).one()
    assert obj.net_income == 9_999_999_999_999


def test_fetch_without_key_raises(monkeypatch) -> None:
    """AC5: DART_API_KEY 미설정 시 명확한 에러."""
    from app.config import settings
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "dart_api_key", SecretStr(""))
    with pytest.raises(DartAdapterError, match="DART_API_KEY"):
        DartAdapter().fetch("00126380", "2024")


def test_parse_amount() -> None:
    """DART 금액 문자열(콤마 포함) 파싱, 빈값/'-'는 None."""
    from app.ingest.dart import _parse_amount

    assert _parse_amount("514,531,948,000,000") == 514_531_948_000_000
    assert _parse_amount("-3,000") == -3000
    assert _parse_amount("") is None
    assert _parse_amount("-") is None
    assert _parse_amount(None) is None


@pytest.mark.skipif(
    not settings_has_key(), reason="DART_API_KEY 없음 — 라이브 테스트 스킵"
)
def test_live_fetch_samsung() -> None:
    """라이브: 삼성전자 실데이터가 매핑되는지(키 있을 때만)."""
    company, fins = DartAdapter().normalize(
        DartAdapter().fetch("00126380", "2024", "11011")
    )
    assert company["market"] == "KOSPI"
    assert company["stock_code"] == "005930"
    assert fins[0]["total_assets"] and fins[0]["total_assets"] > 0
```

## 이미 알려진 것 (중복 지적 불필요)
- DART는 dart-fss 대신 OpenDART REST(requests) 직접 호출로 의도적 전환(dart-fss XBRL 불안정).
- depreciation(감가상각비)은 DART가 다른 라벨로 줘서 현재 null(라벨 보강은 후속, NFR2로 허용).
- 자사주/배당은 별도 공시라 best-effort null(Story 1.6 연계).
- 라이브 삼성전자 수집은 실제로 검증됨(pytest 14 passed).

## 출력 형식
[High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정
