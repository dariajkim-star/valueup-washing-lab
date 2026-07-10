# 코드 리뷰 요청 — 밸류업 워싱 스크리너 Story 1.1 (스캐폴딩 & DB 연결)

너는 엄격한(adversarial) 시니어 코드 리뷰어야. 아래 **스토리/AC**, **아키텍처 제약**, **코드**를 보고
버그·규약 위반·엣지케이스·테스트 허점을 찾아줘. 각 발견은 [심각도 High/Med/Low] + 파일:설명 + 근거 형태로.
칭찬은 생략하고 문제만. 없으면 "clean"이라고 해줘.

## 스토리 & 인수기준(AC)
- As a 개발자, FastAPI 골격 + PostgreSQL 연결 기반을 갖춰 후속 스토리 토대를 만든다.
- AC1: `/health` 200 + `/docs` 렌더
- AC2: config가 .env에서 DB URL·DART_API_KEY·ECOS_API_KEY와 워싱 임계치(0.5/0.6)·Value-up(0.5/0.3/0.2)·M&A(0.35/0.25/0.25/0.15) 가중치 로드 (하드코딩 금지)
- AC3: DB 왕복(SELECT 1) 확인
- AC4: alembic upgrade head 동작(테이블은 후속, 빈 baseline)
- AC5: DB URL이 SQLite면 로컬 폴백 부팅

## 아키텍처 제약 (반드시 확인)
- AD-2: 레이어 단방향 routers→services→repositories→models/DB. 라우터가 DB 직접접근 금지(단 /health의 SELECT 1은 스토리가 예외 승인).
- AD-5: 엔티티 정식 키는 corp_code(8자리) — 이 스토리는 모델 없음, 후속 적용.
- NFR3: 임계치·가중치 하드코딩 금지 → config.

## 변경된 코드 (전부 신규 파일)

### `requirements.txt`
```python
# ── 밸류업 워싱 스크리너 / Python 3.12 ──

# Web framework
fastapi==0.139.0
uvicorn[standard]==0.34.0

# Settings & validation
pydantic==2.10.4
pydantic-settings==2.7.1

# DB / ORM
SQLAlchemy==2.0.51
alembic==1.14.0
psycopg2-binary==2.9.10        # PostgreSQL 드라이버 (개발 SQLite는 표준 라이브러리)

# 데이터 수집 (외부 소스: DART · KRX · ECOS)
dart-fss==0.4.11               # 금융감독원 전자공시 (재무제표 + 밸류업 공시 + 지분구조)
pykrx==1.0.51                  # KRX 시세 / 시가총액 / 거래대금
requests==2.32.3               # 한국은행 ECOS OpenAPI (금리·환율·경기지표)

# 분석
pandas==2.2.3
numpy==2.2.1

# 배치 스케줄러
APScheduler==3.11.0

# 테스트
pytest==8.3.4
httpx==0.28.1                  # FastAPI TestClient 백엔드

# 개발 편의
python-dotenv==1.0.1
```

### `alembic.ini`
```python
# Alembic config. DB URL is injected by env.py from app.config.settings.
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

### `app/config.py`
```python
"""애플리케이션 설정 (pydantic-settings).

임계치·가중치는 절대 코드에 하드코딩하지 않는다(NFR3, AD-4/AD-10).
gap_engine·mna_engine 등 후속 스토리가 여기서 값을 읽는다.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── 앱 ──
    app_name: str = "밸류업 워싱 스크리너"
    debug: bool = False

    # ── DB ── (PostgreSQL 기본, 로컬 개발은 SQLite 폴백 가능)
    database_url: str = "sqlite:///./valueup.db"

    # ── 외부 소스 API 키 (소스 3종: DART · KRX · ECOS) ──
    dart_api_key: str = ""
    ecos_api_key: str = ""

    # ── 워싱 판정 임계치 (scoring.md) ──
    washing_progress_min: float = 0.5       # 목표기간 최소 진척률
    washing_achievement_max: float = 0.6    # 워싱 판정 달성률 상한

    # ── Value-up 실행점수 가중치 (합 1.0) ──
    score_w_achievement: float = 0.5
    score_w_buyback: float = 0.3
    score_w_payout: float = 0.2

    # ── M&A Target Score 가중치 (합 1.0) ──
    mna_w_valuation: float = 0.35
    mna_w_capacity: float = 0.25
    mna_w_ownership: float = 0.25
    mna_w_macro: float = 0.15


settings = Settings()
```

### `app/db.py`
```python
"""DB 엔진/세션 (SQLAlchemy 2.0).

레이어 규약(AD-2): repository만 이 세션으로 SQL을 실행한다.
PostgreSQL 기본, SQLite 폴백(로컬 개발·CI).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# SQLite는 커넥션 스레드 체크 완화가 필요
_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Iterator[Session]:
    """FastAPI 의존성: 요청 스코프 DB 세션."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db() -> bool:
    """헬스체크용 DB 왕복 (SELECT 1)."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return True
```

### `app/main.py`
```python
"""FastAPI 엔트리포인트.

레이어 구조(AD-2): routers → services → repositories → models/DB.
이 스토리는 골격 + /health 만 제공한다.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app import __version__
from app.config import settings
from app.db import check_db

app = FastAPI(title=settings.app_name, version=__version__)


@app.get("/health", tags=["system"])
def health() -> JSONResponse:
    """헬스체크: 앱 기동 + DB 왕복(SELECT 1) 확인.

    DB 정상 → 200 {status:ok, db:ok}
    DB 실패 → 503 {status:degraded, db:down} (모니터링이 상태를 읽게)
    """
    try:
        check_db()
    except Exception:
        return JSONResponse(
            status_code=503, content={"status": "degraded", "db": "down"}
        )
    return JSONResponse(status_code=200, content={"status": "ok", "db": "ok"})
```

### `app/models.py`
```python
"""SQLAlchemy 선언적 Base.

이 스토리(1.1)는 Base만 선언한다. 실제 테이블은 후속 스토리에서 추가:
  - company / financials / prices / valueup_plan / ownership / macro_indicator (Epic 1)
  - valueup_score / mna_score (Epic 2)
엔티티 정식 키는 corp_code(8자리)다(AD-5).
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """모든 ORM 모델의 공통 Base."""

    pass
```

### `alembic/env.py`
```python
"""Alembic 마이그레이션 환경.

DB URL과 target metadata를 app 코드에서 주입한다(단일 진실원천 = app.config).
이 스토리는 빈 baseline이며, 실제 테이블 모델은 후속 스토리에서 app.models에 추가된다.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### `alembic/versions/0001_baseline.py`
```python
"""baseline (빈 초기 리비전)

이 스토리(1.1)는 마이그레이션 환경만 확립한다. 테이블은 후속 스토리에서 추가.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-08
"""
from __future__ import annotations

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 빈 baseline. 테이블은 후속 스토리(1.2~)에서 추가된다.
    pass


def downgrade() -> None:
    pass
```

### `tests/test_health.py`
```python
"""Story 1.1 — 헬스체크 + 설정 로딩 검증."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pytest import approx

from app.config import settings
from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    """AC1·AC3: /health가 200과 status=ok, DB 왕복 확인을 반환한다."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_config_loads_thresholds_and_weights() -> None:
    """AC2: 워싱 임계치·가중치가 설정으로 로드된다(하드코딩 금지)."""
    assert settings.washing_progress_min == 0.5
    assert settings.washing_achievement_max == 0.6
    # Value-up 가중치 합 = 1.0 (부동소수점 허용오차 비교)
    assert (
        settings.score_w_achievement
        + settings.score_w_buyback
        + settings.score_w_payout
    ) == approx(1.0)
    # M&A 가중치 합 = 1.0
    assert (
        settings.mna_w_valuation
        + settings.mna_w_capacity
        + settings.mna_w_ownership
        + settings.mna_w_macro
    ) == approx(1.0)


def test_health_reports_db_down(monkeypatch) -> None:
    """리뷰 반영: DB 실패 시 /health가 503 + db:down을 반환한다(죽은코드 아님)."""
    import app.main as main

    def _boom() -> bool:
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(main, "check_db", _boom)
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "degraded", "db": "down"}


def test_openapi_docs_available() -> None:
    """AC1: OpenAPI 스키마(/docs 소스)가 노출된다."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"]
```

## 이미 알려진 것 (중복 지적 불필요)
- alembic.ini는 ASCII만 사용(Windows cp949 인코딩 이슈로 한글 주석 제거함).
- /health는 DB 실패 시 503 {status:degraded, db:down} 반환(의도된 동작).
- 코드 위치 valueup-washing-lab은 스캐폴딩으로 신규 생성됨.

## 원하는 출력 형식
[High/Med/Low] 파일:라인 — 문제 — 근거/재현조건 — 제안수정
