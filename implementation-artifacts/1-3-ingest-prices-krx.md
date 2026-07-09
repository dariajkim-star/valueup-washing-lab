---
baseline_commit: fde6b860e4de5af73a53d72e6c31110d695f626c
---

# Story 1.3: 시세·시가총액·거래대금 수집 (KRX)

Status: done

### Review Findings (GPT 교차검증 2026-07-08) — 22건 → 11 patch / 5 defer / 2 dismiss

*Patch 적용:*
- [x] [High] **os.environ 비번 전역주입** → `_krx_env` context manager로 pykrx 호출 스코프에서만 주입·원복(env-restore 테스트)
- [x] [High] **cap 실패를 성공처럼 처리** → `cap_ok` 플래그 + `IngestResult.degraded`로 부분성공 명시(시총·거래대금 미수집 표시)
- [x] [High] stock_code 검증 — 6자리 숫자 아니면 `KrxAdapterError`, company 매핑 부재는 preflight로 failed 분리(조용한 skip 금지)
- [x] [Med] CheckConstraint — close/volume/trading_value/market_cap `>= 0`(음수 방지)
- [x] [Med] pykrx 컬럼 스키마 검증 — `_require_columns`로 컬럼 바뀌면 조용한 null 대신 에러
- [x] [Med] volume 충돌 — cap의 거래량은 매핑 안 함(volume=ohlcv 전용) 명시. 문서 모순(get_market_cap 종가) 정리
- [x] [Med] company 선행 의존 preflight — 매핑 없는 corp_code 먼저 failed 반환
- [x] [Low] 날짜 index type — `_to_iso`가 Timestamp·문자열 모두 처리(테스트 추가)
- [x] [Low] .env.example 보안 주석(계정잠금·CI금지·Secret Manager)
- [x] [Low] requirements pykrx 1.0.51 → 1.2.8(Dev Record와 통일)
- [x] [Low] 테스트 보강 — env원복·degraded·스키마·stock_code·string날짜

*Defer(→ deferred-work.md):* 동시성 DB-native upsert / 예외 타입 세분화(KrxAuthError 등) / 병합 결측률 임계치 / 부분일 status / 감사 메타컬럼(ingested_at·source_run_id)
*Dismiss:* 자연키·FK(이미 마이그레이션에 있음) / volume 충돌(cap 거래량 미매핑이라 없음)


## Story

As a 애널리스트,
I want KRX에서 종가·거래량·거래대금·시가총액이 `prices`에 적재되는 것,
so that PBR·PER·EV 계산과 유동성·시총 필터가 가능해진다.

## Acceptance Criteria

1. **Given** `prices` 테이블 모델과 마이그레이션(0003), **When** `alembic upgrade head`, **Then** 테이블 생성. 자연키 (corp_code, date), AD-5 corp_code FK.
2. **Given** `krx_adapter`(SourceAdapter 준수: fetch→normalize→upsert, AD-3), **When** 한 종목 수집, **Then** `prices`(corp_code, date, close, volume, trading_value, market_cap)가 적재된다.
3. **Given** 종목코드 체계, **When** 수집하면, **Then** pykrx는 stock_code(6자리)로 조회하되 저장 키는 corp_code(8자리)다. company 테이블에서 stock_code↔corp_code 매핑(AD-5).
4. **Given** 시가총액, **When** 적재하면, **Then** 시총 단일원천은 `prices`다(AD-9). company에는 저장하지 않는다.
5. **Given** 재실행, **When** 같은 구간을 다시 수집, **Then** (corp_code, date) 멱등 upsert로 중복 없음(AD-7).
6. **Given** KRX 로그인(KRX_ID/KRX_PW) 필요, **When** 미설정 시, **Then** 명확한 에러로 안내(부팅 안 막음).
7. **Given** fixture(가짜 pykrx DataFrame), **When** 정규화·upsert 단위테스트, **Then** 매핑·멱등성 검증(계정 없이 CI).

## Tasks / Subtasks

- [x] **T1: 모델 & 마이그레이션** (AC: 1, 4) — `Price`(corp_code FK, date, close, volume, trading_value, market_cap, 자연키 corp_code+date). 리비전 0003 → upgrade head 검증.
- [x] **T2: config** (AC: 6) — `krx_id`·`krx_pw`(SecretStr) 추가, `.env.example` 갱신.
- [x] **T3: KRX 어댑터** (AC: 2, 3, 6) — `app/ingest/krx.py`. pykrx `get_market_cap`(종가·시총·거래량·거래대금 한 번에) 사용, KRX_ID/KRX_PW를 os.environ 주입, stock_code 조회→corp_code 저장, 미설정 시 `KrxAdapterError`. DataFrame→rows 변환은 순수함수(`_rows_from_df`)로 분리.
- [x] **T4: 멱등 upsert** (AC: 5) — `app/repositories/prices.py` (corp_code, date), None 안 덮음.
- [x] **T5: 수집 트리거** (AC: 2) — `ingest_prices()`, company에서 stock_code 조회(AD-5), 종목별 커밋+실패목록.
- [x] **T6: 테스트** (AC: 5, 7) — `tests/test_krx_ingest.py`(가짜 cap DataFrame으로 매핑·ISO날짜·멱등·키에러). 22 passed.

## Dev Notes

### pykrx — 조사 결과 (탐침 완료)
- `stock.get_market_ohlcv(from, to, ticker)` → DataFrame(index=날짜; 시가·고가·저가·종가·거래량·등락률). **로그인 불필요**. 단, **거래대금·시가총액 없음**.
- `stock.get_market_cap_by_ticker(date, market)` → 종가·**시가총액**·거래량·**거래대금**. **KRX 로그인 필요**(KRX_ID/KRX_PW 환경변수). ← 시총·거래대금 원천.
- pykrx는 `os.environ["KRX_ID"]`, `os.environ["KRX_PW"]`를 읽음 → 어댑터가 settings에서 읽어 os.environ에 주입.
- ticker = stock_code(6자리). corp_code(8자리) 아님 → company에서 매핑(AD-5).

### 아키텍처 제약
- **AD-3**: krx_adapter가 prices의 유일 writer. SourceAdapter 인터페이스 준수(1.2의 base.py 재사용).
- **AD-5**: 저장 키 corp_code. pykrx 조회는 stock_code.
- **AD-9**: 시가총액 단일원천 = prices. company에 없음.
- **AD-7**: (corp_code, date) 멱등 upsert.
- **NFR2**: 값 없으면 null 허용.

### 1.2에서 확립된 패턴 재사용
- `SourceAdapter`(fetch→normalize→upsert), 종목별 커밋+실패목록(`IngestResult`), None으로 기존값 안 덮기, 회계/숫자 파싱 방어.
- 외부 라이브러리 마찰 대응: pykrx 시총이 로그인 필요 → **KRX 계정(KRX_ID/KRX_PW)** 사용(방법 B 결정).

### 소스 트리
```
app/models.py                  # UPDATE: Price
app/config.py                  # UPDATE: krx_id, krx_pw
app/ingest/krx.py              # NEW: KrxAdapter
app/repositories/prices.py     # NEW: 멱등 upsert
app/ingest/run.py              # UPDATE: ingest_prices
alembic/versions/0003_prices.py# NEW
tests/test_krx_ingest.py       # NEW
```

### 테스트 표준
- fixture 기반(가짜 pykrx DataFrame)으로 정규화·멱등성. 라이브는 KRX 계정 확보 시.

### References
- [Source: epics.md#Story-1.3], [db-schema.md] prices(trading_value 포함)
- [Source: ARCHITECTURE-SPINE.md#AD-3,5,7,9]
- [Source: 1-2-ingest-financials-dart.md] SourceAdapter·IngestResult·upsert 패턴
- pykrx: https://github.com/sharebook-kr/pykrx

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (bmad-dev-story)

### Debug Log References
- **KRX 라이브러리 마찰(DART와 유사)**: pykrx 1.2.8은 시총·거래대금 조회에 **KRX 로그인 필요**(KRX_ID/KRX_PW 환경변수). 사용자 결정=방법 B(정확도 우선).
- **KRX 로그인 트러블슈팅**: (1) 카카오 연동 계정이라 초기 비번 거부(CD006 패스워드불일치, 단 회원 인식됨) → 사용자가 KRX native 비번 확인 → (2) CD011(중복로그인)=비번 정확, pykrx가 skipDup=Y로 자동처리 → 로그인 성공. **계정 잠금 위험(loginErrCnt)으로 재시도 루프 없이 1회씩 진단**.
- **close null 버그 발견·수정**: `get_market_cap`은 **종가를 안 줌**(시총·거래량·거래대금·상장주식수만). 종가는 `get_market_ohlcv`(로그인 불필요)에서 와야 함 → **두 소스를 날짜로 병합**(`_merge_frames`). cap 일시 실패해도 종가는 남게 관대 처리.
- **라이브 검증 완료**: 삼성전자 실데이터(종가 79,600·시총 475조·거래대금 1.36조), company→prices end-to-end 적재 확인.
- **stock_code↔corp_code**: pykrx는 stock_code로 조회, 저장은 corp_code. `ingest_prices`가 company에서 매핑(AD-5) → 1.2가 먼저 적재돼야 함(end-to-end 검증됨).

### Completion Notes List
- `Price` 모델 + 마이그레이션 0003 → `prices`(7컬럼) 생성 확인. 시총 단일원천=prices(AD-9).
- `KrxAdapter`가 `SourceAdapter` 인터페이스 준수(1.2 base.py 재사용). DataFrame→rows 순수 분리로 계정 없이 단위테스트.
- 멱등 upsert(corp_code, date), None으로 기존값 안 덮음(1.2 리뷰 교훈 반영).
- `ingest_prices`: 종목별 커밋+실패목록(IngestResult 재사용).
- **검증**: pytest **23 passed**(병합·cap-None 폴백·ISO날짜·멱등·키에러), alembic upgrade head, **라이브 삼성 실데이터 + company→prices end-to-end**.

### File List
- `app/models.py` (UPDATE: Price)
- `app/config.py` (UPDATE: krx_id, krx_pw)
- `app/ingest/krx.py` (NEW: KrxAdapter — ohlcv+cap 병합)
- `app/repositories/prices.py` (NEW: 멱등 upsert)
- `app/ingest/run.py` (UPDATE: ingest_prices)
- `alembic/versions/0003_prices.py` (NEW)
- `tests/test_krx_ingest.py` (NEW)
- `.env.example` (UPDATE: KRX_ID/KRX_PW)
- `.env` (KRX_ID/KRX_PW 추가, gitignored)

## Change Log
- 2026-07-08: Story 1.3 구현 — Price 모델+마이그레이션0003, KRX 어댑터, 멱등 upsert. pytest(fixture).
- 2026-07-08: KRX 계정 확보 → 로그인 트러블슈팅(카카오/CD006/CD011) → **ohlcv+cap 두 소스 병합**(close null 버그 수정) → 라이브 삼성 실데이터·end-to-end 검증. pytest 23 passed.
- 2026-07-08: GPT 교차검증 반영 — 11 patch(os.environ 비번 context manager, cap 실패 degraded 신호, CheckConstraint, 컬럼 스키마 검증, stock_code 검증, preflight, .env 보안주석, pykrx 1.2.8 등). pytest 28 passed, 라이브 재검증(degraded 신호 동작).
