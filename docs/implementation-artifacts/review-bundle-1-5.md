# 코드 리뷰 요청 — 밸류업 워싱 스크리너 Story 1.5 (밸류업 계획공시 수집, DART)

너는 엄격한(adversarial) 시니어 코드 리뷰어야. 아래 스토리/AC·아키텍처 제약·코드를 보고
버그·규약 위반·엣지케이스·보안 문제를 찾아줘. `[High/Med/Low] 파일:라인 — 문제 — 근거/재현 — 제안수정` 형식. 칭찬 생략, 없으면 "clean".

**이번 핵심 = 자유서식 공시의 파싱 정확성 + 네트워크 수집 견고성**이라 특히:
- 정규식 파싱의 **false-positive**(틀린 non-null 값 생성 — 예: 연도를 목표로, 인접 지표 %를 다른 지표로, 부정문을 긍정으로). "못 찾으면 null"은 수용되지만 **틀린 값은 null보다 나쁨**.
- fetch/pagination/document 처리 견고성: list.json 다중페이지 종료조건·무한루프, document.xml(ZIP 바이너리) 해제·비ZIP 응답·부분실패 격리·메모리.
- 멱등 upsert 정확성, 자연키 `(corp_code, disclosure_date)` 무결성(빈/무효 날짜).
- 키/URL 미노출(예외·로그), 인젝션 표면.
- SQLite(개발)/PostgreSQL(운영) 이식성(Boolean/Float/unique).
- 레이어 규약(AD-2/AD-3), 테스트 커버리지(AC6).

## 스토리 & AC
- As a 애널리스트, DART "기업가치 제고 계획" 공시의 목표치(ROE·배당성향·PBR·목표기간·자사주계획)를 구조화 저장 → 2.1 갭 스코어링 입력.
- AC1: valueup_plan 모델 + 마이그레이션 0006, `alembic upgrade head`로 생성. FK corp_code(8자리), 유니크 (corp_code, disclosure_date).
- AC2: dart_adapter 파서로 valueup_plan(target_roe, target_payout_ratio, target_pbr, period_start, period_end, buyback_planned, raw_text) 적재.
- AC3: 파싱 실패 필드 null, 원문 raw_text 항상 보존, 수집 실패 없음(NFR2).
- AC4: 자연키 (corp_code, disclosure_date) 멱등 upsert(AD-7).
- AC5: DART_API_KEY 미설정 시 키/URL 미노출 DartAdapterError.
- AC6: fixture 기반 단위 테스트(라이브 키 없이).

## 아키텍처 제약
- AD-3: dart_adapter가 valueup_plan의 유일 writer(source="dart"), 공통 인터페이스 fetch→normalize→upsert.
- AD-5: corp_code(8자리) FK·정식키. AD-7: 멱등 upsert 자연키.
- AD-2: 수집은 서빙과 분리, repository가 upsert.

## 이미 알려진/의도된 설계 (재지적 불필요)
1) 자유서식이라 목표필드는 best-effort 파싱(못 찾으면 null). 2) raw_text 항상 보존. 3) 주주환원율은 배당성향과 다른 지표라 "배당성향"만 target_payout_ratio에 매핑(주주환원율만 있으면 null). 4) document.xml은 ZIP 바이너리라 JSON `_get`이 아닌 별도 `_fetch_document`(resp.content). 5) 같은 날 동일 disclosure_date는 v1에서 덮어쓰기 허용. 6) pblntf_ty는 과대필터 방지 위해 생략(report_nm 매칭). 7) 테스트 fixture는 별도 파일 대신 인라인. 8) HTTP 하드닝(_RateLimiter·Retry·키 redaction)·_parse_amount·DartAdapterError는 기존 app/ingest/dart.py에서 재사용(그 파일은 검토 완료).

## 변경 코드 (File List 전체)

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
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    String,
    Text,
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


class ValueupPlan(Base):
    """밸류업 계획공시 원천 (writer = dart_adapter, AD-3). 자연키 (corp_code, disclosure_date), AD-7.

    "기업가치 제고 계획"은 자유서식 공시 → 목표 필드는 best-effort 파싱(못 찾으면 null, NFR2).
    원문 raw_text는 항상 보존(재파싱 가능). 목표 지표는 비율/배수라 Float.
    """

    __tablename__ = "valueup_plan"
    __table_args__ = (
        UniqueConstraint("corp_code", "disclosure_date", name="uq_valueup_corp_date"),
    )

    plan_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    disclosure_date: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD (접수일)
    # 목표치 (best-effort 파싱, 없으면 null)
    target_roe: Mapped[float | None] = mapped_column(Float)  # %
    target_payout_ratio: Mapped[float | None] = mapped_column(Float)  # 배당성향 %
    target_pbr: Mapped[float | None] = mapped_column(Float)  # 배
    period_start: Mapped[str | None] = mapped_column(String(10))  # 목표기간 시작(연도/ISO)
    period_end: Mapped[str | None] = mapped_column(String(10))  # 목표기간 종료
    buyback_planned: Mapped[bool | None] = mapped_column(Boolean)  # 자사주 계획 언급 여부
    raw_text: Mapped[str | None] = mapped_column(Text)  # 공시 원문(항상 보존)


class MacroIndicator(Base):
    """매크로 지표 시계열 (writer = ecos_adapter, AD-3). 종목 무관. 자연키 (indicator, date)."""

    __tablename__ = "macro_indicator"
    __table_args__ = (
        UniqueConstraint("indicator", "date", name="uq_macro_indicator_date"),
        CheckConstraint(
            "indicator IN ('base_rate','bond_3y','usd_krw','leading_index')",
            name="ck_macro_indicator_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    indicator: Mapped[str] = mapped_column(String(30), index=True)  # base_rate 등
    date: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD
    value: Mapped[float | None] = mapped_column(Float)
    frequency: Mapped[str | None] = mapped_column(String(1))  # M(월)/D(일) — look-ahead 판별용

```

### `app/ingest/dart_valueup.py`
```python
"""DART 밸류업 계획공시 어댑터 — valueup_plan의 writer (AD-3, source="dart").

"기업가치 제고 계획"은 구조화 재무 API가 없는 **자유서식 공시**라 2단계로 수집한다:
  1) list.json(공시검색, JSON)  → report_nm 매칭으로 밸류업 공시 발견(다중·다중페이지)
  2) document.xml(ZIP 바이너리) → 압축 해제·태그 스트립으로 원문 raw_text 확보

정확성 계약의 핵심은 **raw_text 보존 + 멱등 upsert**. 목표 필드(ROE·배당성향·PBR·기간·자사주)는
raw_text에서 best-effort 정규식 추출이며, 못 찾으면 null(NFR2).

⚠️ document.xml은 JSON이 아니라 ZIP 바이너리 → dart.py의 `_get`(resp.json) 재사용 금지.
   list.json(JSON)만 `_get` 패턴(_get_json)을 쓰고, 문서는 `_fetch_document`(resp.content)로 받는다.
HTTP 하드닝(세션+Retry+_RateLimiter)·키 미노출 예외는 dart.py 패턴을 그대로 재사용.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy.orm import Session
from urllib3.util.retry import Retry

from app.config import settings
from app.ingest.base import SourceAdapter
from app.ingest.dart import (
    _BASE,
    _MIN_INTERVAL,
    _TIMEOUT,
    DartAdapterError,
    _RateLimiter,
)
from app.repositories.valueup_plan import upsert_valueup_plan

# report_nm 매칭(공백 제거 후 부분일치). pblntf_ty로 좁히지 않는다(과대필터 방지).
_REPORT_KEYWORD = "기업가치제고계획"

# ── best-effort 파싱 패턴 ──
_PCT = r"(\d+(?:\.\d+)?)\s*%"
_ROE_RE = re.compile(r"ROE[^0-9%]{0,20}?" + _PCT, re.IGNORECASE)
# ⚠️ '배당성향'만 매칭. 공시는 흔히 '주주환원율'(배당+자사주/순이익)을 쓰는데 이는 배당성향과
#    다른 지표라, 주주환원율만 있으면 target_payout_ratio에 넣지 않는다(거짓 target 금지).
_PAYOUT_RE = re.compile(r"배당성향[^0-9%]{0,20}?" + _PCT)
_PBR_RE = re.compile(r"PBR[^0-9]{0,20}?(\d+(?:\.\d+)?)\s*배?", re.IGNORECASE)
_PERIOD_RE = re.compile(r"(20\d{2})\s*년?\s*[~\-–∼]\s*(20\d{2})")
_BUYBACK_RE = re.compile(r"(자기주식|자사주)[^\n]{0,20}?(취득|매입|소각)")


def _to_iso(yyyymmdd: str) -> str:
    """DART 접수일 YYYYMMDD → ISO YYYY-MM-DD. 형식이 아니면 원문 유지."""
    s = (yyyymmdd or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _strip_tags(s: str) -> str:
    """DART 전용 XML 마크업(dsd; 깔끔한 HTML 아님) 태그 제거 → 평문."""
    no_tags = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", no_tags).strip()


def _zip_to_text(content: bytes) -> str:
    """document.xml ZIP 바이너리 → 평문 raw_text. ZIP이 아니면(에러응답 등) 빈 문자열."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return ""
    parts: list[str] = []
    with zf:
        for name in zf.namelist():
            parts.append(_decode(zf.read(name)))
    return _strip_tags(" ".join(parts))


def parse_targets(raw_text: str | None) -> dict[str, Any]:
    """raw_text에서 목표 필드를 best-effort 추출. 못 찾으면 해당 필드 None(NFR2)."""
    text = raw_text or ""

    def _num(rx: re.Pattern[str]) -> float | None:
        m = rx.search(text)
        return float(m.group(1)) if m else None

    pm = _PERIOD_RE.search(text)
    return {
        "target_roe": _num(_ROE_RE),
        "target_payout_ratio": _num(_PAYOUT_RE),
        "target_pbr": _num(_PBR_RE),
        "period_start": pm.group(1) if pm else None,
        "period_end": pm.group(2) if pm else None,
        # 자사주 계획 키워드 있으면 True, 없으면 None(부재를 단정하지 않음)
        "buyback_planned": True if _BUYBACK_RE.search(text) else None,
    }


class DartValueupAdapter(SourceAdapter):
    source = "dart"

    def __init__(self) -> None:
        self._session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._limiter = _RateLimiter(_MIN_INTERVAL)

    # ── fetch (라이브, 키 필요) ──
    def fetch(self, corp_code: str, bgn_de: str, end_de: str) -> dict[str, Any]:
        key = settings.dart_api_key.get_secret_value()
        if not key:
            raise DartAdapterError(
                "DART_API_KEY가 설정되지 않았습니다. .env에 DART_API_KEY를 넣으세요."
            )
        plans: list[dict[str, Any]] = []
        page_no = 1
        while True:
            data = self._get_json(
                "list.json",
                {
                    "crtfc_key": key,
                    "corp_code": corp_code,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                    "page_no": page_no,
                    "page_count": 100,
                },
                allow_no_data=True,
            )
            for item in data.get("list") or []:
                report_nm = item.get("report_nm", "")
                if _REPORT_KEYWORD in report_nm.replace(" ", ""):
                    rcept_no = item.get("rcept_no")
                    raw_text = self._fetch_document(key, rcept_no) if rcept_no else ""
                    plans.append(
                        {
                            "disclosure_date": _to_iso(item.get("rcept_dt", "")),
                            "report_nm": report_nm,
                            "raw_text": raw_text,
                        }
                    )
            total_page = int(data.get("total_page") or 1)
            if page_no >= total_page:
                break
            page_no += 1
        return {"corp_code": corp_code, "plans": plans}

    def _get_json(
        self, endpoint: str, params: Mapping[str, Any], allow_no_data: bool = False
    ) -> dict[str, Any]:
        """list.json 등 JSON 엔드포인트. dart.py `_get`과 동일한 status 처리. 키 미노출."""
        self._limiter.acquire()
        try:
            resp = self._session.get(
                f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise DartAdapterError(
                f"DART 요청 실패: endpoint={endpoint} ({type(e).__name__})"
            ) from None
        status = data.get("status")
        if status == "000":
            return data
        if allow_no_data and status == "013":  # 조회된 데이터 없음
            return {"list": []}
        raise DartAdapterError(
            f"DART API 오류: endpoint={endpoint}, status={status}, "
            f"msg={data.get('message')}"
        )

    def _fetch_document(self, key: str, rcept_no: str) -> str:
        """document.xml(ZIP 바이너리) 다운로드 → 평문. resp.json 금지(바이너리)."""
        self._limiter.acquire()
        try:
            resp = self._session.get(
                f"{_BASE}/document.xml",
                params={"crtfc_key": key, "rcept_no": rcept_no},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.content  # 바이너리(ZIP)
        except requests.RequestException as e:
            raise DartAdapterError(
                f"DART 문서 다운로드 실패: ({type(e).__name__})"
            ) from None
        return _zip_to_text(content)

    # ── normalize (순수, 테스트 가능) ──
    def normalize(self, raw: Mapping[str, Any]) -> list[dict[str, Any]]:
        corp_code = raw["corp_code"]
        recs: list[dict[str, Any]] = []
        for plan in raw.get("plans", []):
            rec: dict[str, Any] = {
                "corp_code": corp_code,
                "disclosure_date": plan["disclosure_date"],
                "raw_text": plan.get("raw_text"),
            }
            rec.update(parse_targets(plan.get("raw_text")))
            recs.append(rec)
        return recs

    # ── upsert (멱등) ──
    def upsert(self, session: Session, records: Sequence[dict[str, Any]]) -> int:
        for rec in records:
            upsert_valueup_plan(session, rec)
        session.flush()
        return len(records)

```

### `app/repositories/valueup_plan.py`
```python
"""valueup_plan 멱등 upsert 저장소.

수집 경로 전용(서빙 아님). 자연키 (corp_code, disclosure_date) 기준으로
존재하면 갱신, 없으면 삽입 → 재실행 안전(AD-7).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ValueupPlan

# 목표 필드: None이면 기존 non-null을 덮어쓰지 않는다(일시적 파싱 실패로 값 삭제 방지).
_TARGET_FIELDS = (
    "target_roe",
    "target_payout_ratio",
    "target_pbr",
    "period_start",
    "period_end",
    "buyback_planned",
)


def upsert_valueup_plan(session: Session, rec: dict) -> ValueupPlan:
    """(corp_code, disclosure_date) 자연키 기준 valueup_plan upsert."""
    stmt = select(ValueupPlan).where(
        ValueupPlan.corp_code == rec["corp_code"],
        ValueupPlan.disclosure_date == rec["disclosure_date"],
    )
    obj = session.scalars(stmt).one_or_none()
    if obj is None:
        obj = ValueupPlan(
            corp_code=rec["corp_code"], disclosure_date=rec["disclosure_date"]
        )
        session.add(obj)
    # 목표 필드는 None이 아닐 때만 갱신(파싱 실패로 기존값 소실 방지)
    for field in _TARGET_FIELDS:
        if rec.get(field) is not None:
            setattr(obj, field, rec[field])
    # 원문은 항상 반영(원천 보존이 목적) — 키가 있으면 값이 None이어도 저장
    if "raw_text" in rec:
        obj.raw_text = rec["raw_text"]
    return obj

```

### `alembic/versions/0006_valueup_plan.py`
```python
"""valueup_plan table

Revision ID: 0006_valueup_plan
Revises: 0005_valuation_metrics_view
Create Date: 2026-07-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_valueup_plan"
down_revision: str | None = "0005_valuation_metrics_view"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "valueup_plan",
        sa.Column("plan_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "corp_code",
            sa.String(length=8),
            sa.ForeignKey("company.corp_code"),
            nullable=False,
            index=True,
        ),
        sa.Column("disclosure_date", sa.String(length=10), nullable=False),
        sa.Column("target_roe", sa.Float),
        sa.Column("target_payout_ratio", sa.Float),
        sa.Column("target_pbr", sa.Float),
        sa.Column("period_start", sa.String(length=10)),
        sa.Column("period_end", sa.String(length=10)),
        sa.Column("buyback_planned", sa.Boolean),
        sa.Column("raw_text", sa.Text),
        sa.UniqueConstraint(
            "corp_code", "disclosure_date", name="uq_valueup_corp_date"
        ),
    )


def downgrade() -> None:
    op.drop_table("valueup_plan")

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
from app.ingest.dart_valueup import DartValueupAdapter
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


def ingest_valueup_plans(
    corp_codes: Sequence[str], date_from: str, date_to: str
) -> IngestResult:
    """종목별 밸류업 계획공시(DART) 수집. [date_from, date_to]는 YYYYMMDD(bgn_de/end_de).

    한 종목이 예고·본공시·정정 등 여러 공시를 내면 각각 valueup_plan 행이 된다.
    실패는 건너뛰고 목록에 담는다(부분성공). fetch(네트워크)는 짧은 트랜잭션 밖.
    """
    adapter = DartValueupAdapter()
    result = IngestResult()
    for corp_code in corp_codes:
        try:
            raw = adapter.fetch(corp_code, date_from, date_to)  # 네트워크(트랜잭션 밖)
            records = adapter.normalize(raw)
            with SessionLocal() as session:  # 종목당 짧은 트랜잭션
                with session.begin():
                    n = adapter.upsert(session, records)
            result.ingested += n
            result.succeeded.append(corp_code)
        except Exception as e:  # noqa: BLE001 (부분성공 정책)
            logger.warning(
                "밸류업 공시 수집 실패 corp_code=%s: %s", corp_code, type(e).__name__
            )
            result.failed.append((corp_code, str(e)))
    return result


def ingest_macro(date_from: str, date_to: str) -> IngestResult:
    """ECOS 매크로 지표(4종)를 [date_from, date_to](YYYYMMDD) 수집·적재.

    지표별 실패는 격리(fetch가 지표별로 잡아 raw['failed'] 반환) → result.failed에 표시.
    """
    adapter = EcosAdapter()
    result = IngestResult()
    try:
        raw = adapter.fetch(date_from, date_to)
        records = adapter.normalize(raw)
        with SessionLocal() as session:
            with session.begin():
                result.ingested = adapter.upsert(session, records)
        for indicator, reason in raw.get("failed", []):
            logger.warning("매크로 지표 실패 %s: %s", indicator, reason)
            result.failed.append((indicator, reason))
        # 성공한(=실패 목록에 없는) 지표
        failed_names = {i for i, _ in raw.get("failed", [])}
        result.succeeded.extend(
            i for i in ("base_rate", "bond_3y", "usd_krw", "leading_index")
            if i not in failed_names
        )
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

### `tests/test_valueup_ingest.py`
```python
"""Story 1.5 — 밸류업 공시 어댑터 파싱·멱등 upsert 검증 (라이브 키 없이 fixture)."""

from __future__ import annotations

import io
import zipfile

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.ingest.dart import DartAdapterError
from app.ingest.dart_valueup import (
    DartValueupAdapter,
    _strip_tags,
    _zip_to_text,
    parse_targets,
)
from app.models import Base, Company, ValueupPlan

# 가짜 공시 원문(자유서식 텍스트)
SAMPLE = (
    "당사는 기업가치 제고 계획을 다음과 같이 공시합니다. "
    "목표 ROE 10% 이상을 2024년 ~ 2026년 기간 동안 달성하고, "
    "배당성향 30%를 목표로 합니다. 목표 PBR 1.0배. "
    "주주가치 제고를 위해 자기주식 취득 및 소각을 계획합니다."
)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Company(corp_code="00000001", corp_name="테스트"))
        s.commit()
        yield s


def test_parse_targets_extracts_all() -> None:
    """AC2: raw_text에서 목표필드가 추출된다."""
    t = parse_targets(SAMPLE)
    assert t["target_roe"] == 10.0
    assert t["target_payout_ratio"] == 30.0
    assert t["target_pbr"] == 1.0
    assert t["period_start"] == "2024"
    assert t["period_end"] == "2026"
    assert t["buyback_planned"] is True


def test_parse_targets_missing_is_null() -> None:
    """AC3/NFR2: 목표 수치가 없으면 해당 필드 null, 수집 실패 없음."""
    t = parse_targets("기업가치 제고 계획 공시. 구체적 목표 수치는 추후 공시.")
    assert t["target_roe"] is None
    assert t["target_payout_ratio"] is None
    assert t["target_pbr"] is None
    assert t["period_start"] is None
    assert t["buyback_planned"] is None


def test_payout_only_matches_배당성향_not_주주환원율() -> None:
    """리뷰 E1: 주주환원율은 배당성향과 다른 지표 → target_payout_ratio에 넣지 않는다."""
    t = parse_targets("주주환원율 35%를 목표로 합니다.")  # 배당성향 언급 없음
    assert t["target_payout_ratio"] is None
    t2 = parse_targets("배당성향 25% 목표")
    assert t2["target_payout_ratio"] == 25.0


def test_zip_to_text_and_strip() -> None:
    """리뷰 C1/M1: document.xml ZIP 바이너리를 풀고 dsd XML 태그를 스트립한다."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("doc.xml", "<DOCUMENT><P>목표 ROE 10%</P></DOCUMENT>".encode("utf-8"))
    text = _zip_to_text(buf.getvalue())
    assert "목표 ROE 10%" in text
    assert "<" not in text and ">" not in text
    # ZIP이 아니면(에러응답 등) 빈 문자열 — 실패 아님
    assert _zip_to_text(b"not a zip") == ""
    assert _strip_tags("<a>x</a> <b>y</b>") == "x y"


def test_normalize_preserves_raw_text() -> None:
    """AC2/AC3: normalize가 목표필드 + raw_text 원문을 레코드로 만든다."""
    raw = {
        "corp_code": "00000001",
        "plans": [
            {"disclosure_date": "2024-03-15", "report_nm": "기업가치 제고 계획",
             "raw_text": SAMPLE},
        ],
    }
    recs = DartValueupAdapter().normalize(raw)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["corp_code"] == "00000001"
    assert rec["disclosure_date"] == "2024-03-15"
    assert rec["target_roe"] == 10.0
    assert rec["raw_text"] == SAMPLE  # 원문 보존


def test_upsert_idempotent_and_updates(session: Session) -> None:
    """AC4: (corp_code, disclosure_date) 자연키 멱등 — 재실행 중복 없음, 값 갱신."""
    adapter = DartValueupAdapter()
    raw = {
        "corp_code": "00000001",
        "plans": [
            {"disclosure_date": "2024-03-15", "raw_text": SAMPLE},
        ],
    }
    recs = adapter.normalize(raw)
    adapter.upsert(session, recs)
    session.commit()
    adapter.upsert(session, recs)  # 재실행
    session.commit()
    assert session.scalar(select(func.count()).select_from(ValueupPlan)) == 1

    recs[0]["target_roe"] = 12.5  # 값 변경 후 재적재
    adapter.upsert(session, recs)
    session.commit()
    obj = session.scalars(select(ValueupPlan)).one()
    assert obj.target_roe == 12.5
    assert obj.raw_text == SAMPLE


def test_multiple_disclosures_multiple_rows(session: Session) -> None:
    """리뷰 E2: 한 종목이 여러 공시(예고·본공시) → 날짜별 행."""
    adapter = DartValueupAdapter()
    raw = {
        "corp_code": "00000001",
        "plans": [
            {"disclosure_date": "2024-03-15", "raw_text": "배당성향 20% 목표"},
            {"disclosure_date": "2024-09-20", "raw_text": "배당성향 30% 목표"},
        ],
    }
    adapter.upsert(session, adapter.normalize(raw))
    session.commit()
    assert session.scalar(select(func.count()).select_from(ValueupPlan)) == 2


def test_fetch_without_key_raises(monkeypatch) -> None:
    """AC5: DART_API_KEY 미설정 시 명확한 에러(키/URL 미노출)."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "dart_api_key", SecretStr(""))
    with pytest.raises(DartAdapterError, match="DART_API_KEY"):
        DartValueupAdapter().fetch("00000001", "20240101", "20241231")

```
