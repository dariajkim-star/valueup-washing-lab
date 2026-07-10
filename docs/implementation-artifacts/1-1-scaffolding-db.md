---
baseline_commit: fde6b860e4de5af73a53d72e6c31110d695f626c
---

# Story 1.1: 프로젝트 스캐폴딩 & DB 연결

Status: done

## Story

As a 개발자,
I want FastAPI 앱 골격과 PostgreSQL 연결·설정(config) 기반을 갖추는 것,
so that 이후 수집·지표·스코어링 스토리(1.2~)가 올라갈 토대가 생긴다.

## Acceptance Criteria

1. **Given** 확정된 스택(FastAPI 0.139 / SQLAlchemy 2.0.51 / PostgreSQL 17), **When** 앱을 실행하면, **Then** `GET /health`가 200과 `{"status":"ok"}`를 반환하고 `/docs`(Swagger)가 렌더된다.
2. **Given** `.env` 파일, **When** 앱이 부팅하면, **Then** `config.py`가 DB URL·`DART_API_KEY`·`ECOS_API_KEY`와 워싱 임계치(0.5/0.6)·Value-up 가중치(0.5/0.3/0.2)·M&A 가중치(0.35/0.25/0.25/0.15)를 로드한다(NFR3).
3. **Given** PostgreSQL 인스턴스, **When** 앱이 부팅하면, **Then** SQLAlchemy 엔진/세션이 연결되고 헬스체크가 DB 왕복(`SELECT 1`)을 확인한다.
4. **Given** alembic 초기화, **When** `alembic upgrade head`를 실행하면, **Then** 마이그레이션 환경이 동작한다(테이블은 후속 스토리에서 추가 — 이 스토리는 빈 baseline).
5. **Given** 개발 폴백, **When** DB URL이 SQLite면, **Then** 로컬에서도 부팅된다(PostgreSQL 미설치 개발자 대비).

## Tasks / Subtasks

- [x] **T1: 프로젝트 골격** (AC: 1)
  - [x] `app/main.py` — FastAPI 앱, `/health` 라우트, `/docs` 활성
  - [x] `app/__init__.py`, 패키지 구조(`routers/`, `services/`, `repositories/`, `ingest/`, `analysis/` 빈 패키지)
  - [x] `requirements.txt` 재생성·정합(FastAPI 0.139.0, SQLAlchemy 2.0.51, 소스 3종 DART·KRX·ECOS)
- [x] **T2: 설정 계층** (AC: 2)
  - [x] `app/config.py` — pydantic-settings `Settings`(DB URL, DART_API_KEY, ECOS_API_KEY, 워싱/Value-up/M&A 파라미터)
  - [x] `.env.example` 작성(키·임계치·가중치 기본값), `.gitignore`에 `.env`
- [x] **T3: DB 연결** (AC: 3, 5)
  - [x] `app/db.py` — SQLAlchemy 2.0 엔진/`Session`, `get_db` 의존성. PostgreSQL 기본, SQLite 폴백
  - [x] `/health`에서 `SELECT 1` 왕복 확인(`check_db`)
- [x] **T4: 마이그레이션** (AC: 4)
  - [x] `alembic/`(env.py·script.py.mako·0001_baseline), `env.py`가 `config.py` DB URL·`models` metadata 참조
  - [x] 빈 baseline 리비전 생성 → `alembic upgrade head` 검증
- [x] **T5: 테스트** (AC: 1, 3)
  - [x] `tests/test_health.py` — TestClient `/health` 200 + config + openapi 검증
  - [x] `pytest` 통과 (3 passed)

## Dev Notes

### 아키텍처 제약 (반드시 준수)
- **레이어 방향(AD-2)**: `routers → services → repositories → models/DB` 단방향. 이 스토리에선 빈 패키지만 만들되 이 구조를 확립. 라우터가 DB 직접 접근 금지(단 `/health`의 `SELECT 1`은 예외적 허용 — repository 없이도 됨, 또는 간단 healthcheck 함수).
- **설정(NFR3)**: 워싱 임계치·가중치는 절대 하드코딩 금지 → 반드시 `config.py`. 후속 스토리(2.1/2.3 엔진)가 여기서 읽는다.
- **소스 키(NFR4)**: `.env`에 `DART_API_KEY`, `ECOS_API_KEY`. (금융공공데이터 키 없음 — 소스 3종 DART·KRX·ECOS)
- **엔티티 키(AD-5)**: 아직 모델 없음. 후속 스토리에서 `corp_code`(8자리)가 PK/FK 정식 키가 됨 — 지금 문서화만.

### 소스 트리 (이 스토리가 만드는 것)
```
valueup-washing-lab/
├── app/
│   ├── __init__.py
│   ├── main.py          # NEW: FastAPI + /health
│   ├── config.py        # NEW: pydantic-settings
│   ├── db.py            # NEW: 엔진/세션
│   ├── models.py        # NEW: 빈 Base(선언만, 테이블은 후속)
│   ├── routers/         # NEW: 빈 패키지
│   ├── services/        # NEW: 빈 패키지
│   ├── repositories/    # NEW: 빈 패키지
│   ├── ingest/          # NEW: 빈 패키지 (dart/krx/ecos는 1.2~1.6)
│   └── analysis/        # NEW: 빈 패키지 (gap/mna 엔진은 2.x)
├── alembic/             # NEW: 마이그레이션 (빈 baseline)
├── alembic.ini          # NEW
├── tests/
│   └── test_health.py   # NEW
├── .env.example         # NEW
├── requirements.txt     # UPDATE: 버전 정합
├── DEV_PLAN.md          # 기존
└── API_SPEC.md          # 기존
```

### 테스트 표준
- pytest + httpx TestClient. 이 스토리는 `/health` 200 + DB 왕복만 검증하면 충분.
- DB 테스트는 SQLite in-memory로 가볍게(외부 PostgreSQL 의존 없이 CI 가능하게).

### Project Structure Notes
- 코드 위치: `C:\Users\user\Desktop\valueup-washing-lab` (기존 DEV_PLAN.md·API_SPEC.md·requirements.txt 존재, `app/` 폴더 이미 있음).
- 기존 requirements.txt에 FastAPI 0.115가 있었으나 아키텍처 확정 버전은 **0.139.0** → 갱신. SQLAlchemy **2.0.51**로 갱신. `dart-fss`/`pykrx` 유지, `requests`(ECOS)로 주석 변경, 금융공공데이터 관련 제거.
- 프론트(React 19+Vite 8)는 이 스토리 범위 아님(Epic 3, Story 3.3~). `frontend/`는 나중에.

### References
- [Source: ARCHITECTURE-SPINE.md#Design-Paradigm] — Layered 서빙 + Pipes-filters 수집, 폴더 구조
- [Source: ARCHITECTURE-SPINE.md#AD-2] — 레이어 단방향 의존
- [Source: ARCHITECTURE-SPINE.md#Stack] — FastAPI 0.139.0, SQLAlchemy 2.0.51, PostgreSQL 17, alembic
- [Source: epics.md#Story-1.1] — AC 원본
- [Source: spec/stack.md] — 폴더 구조·규약, config 파라미터
- [Source: spec/scoring.md] — config로 노출할 임계치·가중치 값

### Review Findings (code review 2026-07-08)

**라운드 1 (인라인 리뷰, Claude)**
- [x] [Review][Decision→Patch] health() DB-down 처리 — `try/except`로 감싸 DB 실패 시 **503 `{status:degraded, db:down}`** 반환(죽은 코드 제거, 모니터링 가독). 검증 테스트 `test_health_reports_db_down` 추가.
- [x] [Review][Patch] 테스트 가중치 합 부동소수점 등식 — `pytest.approx(1.0)`로 교체.

**라운드 2 (GPT 교차검증)** — 다른 LLM 리뷰로 11 patch / 2 defer / 2 dismiss
- [x] [Patch] SecretStr — `database_url`·`dart_api_key`·`ecos_api_key`를 SecretStr로(로그·에러 노출 방지) + `hide_input_in_errors`. db.py·alembic은 `get_secret_value()`.
- [x] [Patch] **alembic `%` interpolation 버그** — `set_main_option`에 `.replace("%","%%")` 이스케이프(비밀번호 `%` 대응).
- [x] [Patch] `pool_pre_ping=True`·`pool_recycle=1800`(PostgreSQL stale 커넥션 false negative 방지).
- [x] [Patch] config 검증 — 가중치 그룹 합≈1.0 `@model_validator`, 임계치·가중치 `Field(ge=0,le=1)`.
- [x] [Patch] `get_db` 예외 시 `rollback()` 명시.
- [x] [Patch] `expire_on_commit=False`(DetachedInstanceError 예방).
- [x] [Patch] `check_db` `SELECT 1` → `.scalar_one()`(응답 실제 소비).
- [x] [Patch] `.env` 경로를 프로젝트 루트로 고정(cwd 비의존).
- [x] [Patch] SQLite 판별 `make_url().get_backend_name()`(문자열 prefix 탈피).
- [x] [Patch] `/docs` HTML 렌더 테스트 추가(AC1).
- [x] [Patch] env 로딩 테스트 + 가중치합 실패 테스트 + `alembic upgrade head` 서브프로세스 테스트 추가(AC2·AC4 자동화).
- [x] [Defer] API 키 필수화(Field(...)) → 키가 실제 필요한 Story 1.2(DART 수집)에서.
- [x] [Defer] `extra="forbid"`(오타 방지) → 유연성 트레이드오프, 후속 검토.
- [x] [Dismiss] `__version__` import 깨짐 — 오탐(app/__init__.py 존재, 번들 누락으로 GPT 오인).
- [x] [Dismiss] "기본값=하드코딩 위반" — pydantic Settings 기본값+env 오버라이드는 정석 패턴(NFR3 충족).

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (bmad-dev-story)

### Debug Log References
- **버그 발견·수정**: `alembic.ini`의 한글 주석이 Windows cp949 환경에서 `configparser` `UnicodeDecodeError` 유발 → ini를 ASCII로 변경. (실제 실행에서만 드러나는 인코딩 이슈)
- 코드 위치 `valueup-washing-lab` 폴더가 실행 시점에 부재(원인 불명) → 스캐폴딩 스토리이므로 신규 생성. 기존 DEV_PLAN/API_SPEC 내용은 SPEC·옵시디언에 보존됨.

### Completion Notes List
- FastAPI 골격 + `/health`(DB `SELECT 1` 왕복 포함) + `/docs` 동작 확인(라이브 uvicorn 200).
- `config.py`: 워싱 임계치·Value-up/M&A 가중치를 설정으로 노출(하드코딩 없음, NFR3). 가중치 합 1.0 테스트로 검증.
- `db.py`: PostgreSQL 기본 + SQLite 폴백(`check_same_thread` 처리). 로컬은 SQLite로 부팅.
- alembic 빈 baseline(0001) → `upgrade head` 성공. 테이블은 후속 스토리.
- 레이어 패키지(routers/services/repositories/ingest/analysis) 빈 골격으로 AD-2 구조 확립.
- **검증**: `pytest` 3 passed, 라이브 서버 `/health`→200 `{status:ok,db:ok}`, `/docs`→200, `alembic current`→0001_baseline(head).

### File List
- `valueup-washing-lab/requirements.txt` (재생성)
- `valueup-washing-lab/.env.example` (신규)
- `valueup-washing-lab/.gitignore` (신규)
- `valueup-washing-lab/alembic.ini` (신규)
- `valueup-washing-lab/app/__init__.py` (신규)
- `valueup-washing-lab/app/config.py` (신규)
- `valueup-washing-lab/app/db.py` (신규)
- `valueup-washing-lab/app/models.py` (신규)
- `valueup-washing-lab/app/main.py` (신규)
- `valueup-washing-lab/app/{routers,services,repositories,ingest,analysis}/__init__.py` (신규, 빈 패키지)
- `valueup-washing-lab/alembic/env.py` (신규)
- `valueup-washing-lab/alembic/script.py.mako` (신규)
- `valueup-washing-lab/alembic/versions/0001_baseline.py` (신규)
- `valueup-washing-lab/tests/__init__.py`, `tests/test_health.py` (신규)

## Change Log
- 2026-07-08: Story 1.1 구현 — FastAPI 스캐폴딩 + PostgreSQL/SQLite DB 연결 + config + alembic baseline. pytest 3 passed, 라이브 검증 완료. (alembic.ini cp949 인코딩 버그 수정 포함)
- 2026-07-08: 코드 리뷰 반영 — 2건 해소. /health DB실패 시 503 db:down 우아하게 반환(죽은코드 제거) + db-down 테스트 추가, 가중치 합 테스트 pytest.approx로. pytest 4 passed.
- 2026-07-08: GPT 교차검증 반영 — 11 patch 적용(SecretStr 시크릿 마스킹, alembic % 버그, pool_pre_ping, config validator, rollback, expire_on_commit, scalar_one, .env 루트고정, make_url, /docs·env·alembic 테스트). 2 defer(키 필수화·extra forbid), 2 dismiss(오탐). pytest 8 passed, 라이브 검증(시크릿 마스킹 확인).
