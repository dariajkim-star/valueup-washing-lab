---
baseline_commit: a43c3c69a6ad5545fda46f2635fc2d5303c778a8
---

# Story 1.8: 자기주식 취득/소각 수집 (DART 자기주식 취득·처분 현황)

Status: done

## Story

As a 애널리스트,
I want DART 자기주식 취득·처분 현황(`tesstkAcqsDspsSttus`)의 취득·소각 신호가 `financials`에 채워지는 것,
so that 워싱 판정(2.2)의 "진짜 소각(NOT buyback_retired)"과 실행점수(2.1)의 자사주 이행 신호를 **실데이터**로 잴 수 있다(현재 두 필드는 구조적 100% null).

## 배경 (왜 이 스토리인가)

1-2 재무제표(`fnlttSinglAcntAll`)에는 자사주 취득/소각 라인이 없어 `DartAdapter`가 `financials.buyback_amount`·`buyback_retired_amount`를 **한 번도 채운 적이 없다**(`normalize`가 `period.get("buyback_amount")`로 읽지만 `fetch`가 그 키를 만들지 않음 → 항상 None). 그런데 2.1이 이 두 필드에서 `buyback_executed`·`buyback_retired`·`buyback_status`를 도출하고, 2.2 워싱 플래그가 `AND NOT buyback_retired`에 의존한다. 데이터 없이 엔진을 붙이면 `buyback_retired`가 전 종목 False로 고정 → 워싱 항이 조용히 상수가 된다(보수적 null이 아니라 **틀린 상수**). 정밀 출처 `tesstkAcqsDspsSttus`를 확보해 이 공백을 메운다. 1-6 known-limitations(line 131)이 이 스토리를 이미 예고함.

> **배치 결정(2026-07-10, 리드)**: 수집 스토리라 Epic 1 테마('데이터 기반')에 배치(Story 1.8, epic-1 재개). Epic 2는 '순수 계산'으로 유지. 적재 타깃은 **기존 `financials` 재사용**(신규 테이블·마이그레이션 없음).

## Acceptance Criteria

1. **Given** `DartAdapter`(financials의 유일 writer, AD-3, source="dart"), **When** 한 종목을 `fetch(corp_code, bsns_year, reprt_code)`로 수집하면, **Then** 기존 company·재무제표 호출에 더해 `tesstkAcqsDspsSttus.json`를 호출해 자기주식 취득/처분 행을 받아온다(별도 어댑터 신설 금지 — financials 단일 writer 유지).
2. **Given** 취득/처분 현황 응답, **When** `normalize`가 집계하면, **Then** 해당 재무 period의 `buyback_amount`(취득 신호)·`buyback_retired_amount`(소각 신호)가 채워진다. **소각 = `change_qy_incnr`(변동수량 소각) 합, 취득 = `change_qy_acqs`(변동수량 취득) 합**.
3. **Given** 응답의 `acqs_mth1/2/3`(취득방법 대·중·소분류)에 **총계/소계/합계 요약행**이 섞일 수 있음, **When** 집계하면, **Then** 요약행을 제외한 leaf 행만 합산해 **이중집계를 방지**한다(1-6 소계 이중가산 교훈). 애매하면 null.
4. **Given** 미공시(status 013/빈 응답)와 "공시했으나 이번 기간 활동 0"은 다름, **When** 집계하면, **Then** **미공시 → null**(기존 값 안 덮음), **공시+활동 0 → 정수 0**(known: 취득/소각 없음), **행은 있으나 전부 파싱 실패 → null**로 구분한다(NFR2 "null > 틀린 값").
5. **Given** 재무제표 수집(`ingest_financials`)과 동일 경로, **When** 같은 배치를 재실행하면, **Then** 자연키 `(corp_code, year, quarter)` 기준 **멱등 upsert**로 buyback 필드가 갱신되고 다른 재무 필드는 보존된다(AD-7, `upsert_financial` None-safe 재사용).
6. **Given** `DART_API_KEY` 미설정, **When** 라이브 수집을 시도하면, **Then** 키/URL을 노출하지 않는 `DartAdapterError`로 안내한다(1.2/1.5/1.6과 동일 정책).
7. **Given** fixture(가짜 `tesstkAcqsDspsSttus` 응답), **When** 집계·upsert 단위 테스트를 돌리면, **Then** 취득/소각 집계·요약행 제외·미공시 null·활동0 구분·멱등성이 라이브 키 없이 검증되고 **기존 78 테스트 회귀 0**.

## Tasks / Subtasks

- [x] **T1: `DartAdapter.fetch` 확장 — 취득/처분 현황 호출** (AC: 1, 6) — `app/ingest/dart.py`. company·`_fetch_accounts` 뒤에 `tesstkAcqsDspsSttus.json`를 `self._get(..., allow_no_data=True)`로 호출(status 013→빈 리스트). params는 재무제표와 동일(`crtfc_key`·`corp_code`·`bsns_year`·`reprt_code`). 받은 `list`를 period dict에 `buyback_rows`로 부착. **재무 period가 생성되는 경우에만**(기존 `if accounts:` 블록) 첫 period에 부착 — buyback만 있고 accounts 없는 종목은 엣지로 문서화(드묾). `include_buyback: bool = True` 파라미터로 노출(테스트·선택적 스킵용).
- [x] **T2: `normalize` 확장 + `_buyback_totals` 헬퍼** (AC: 2, 3, 4) — `app/ingest/dart.py`. 순수 함수 `_buyback_totals(rows) -> tuple[int|None, int|None]` 신규: (1) 요약행(`acqs_mth1/2/3` 중 하나라도 "총계/소계/합계") 제외, (2) leaf 행에서 `change_qy_acqs`·`change_qy_incnr`를 `_parse_amount`로 합산, (3) 파싱 성공 행이 하나도 없으면 `(None, None)`, 있으면 합(0 가능). `normalize`의 period 루프에서 `rec["buyback_amount"], rec["buyback_retired_amount"] = _buyback_totals(period.get("buyback_rows", []))`로 대체(기존 `period.get("buyback_amount")` 라인 교체).
- [x] **T3: 모델 주석 의미 정정 — 수량 presence-proxy 명시** (AC: 2) — `app/models.py:76-77`. 필드는 유지하되 주석을 "**취득/소각 수량(주) — 워싱 presence 신호(>0), KRW 액수 아님**"으로 갱신. **마이그레이션 불필요**(컬럼 이미 존재, 타입 BigInteger 유지). db-schema.md에도 각주 1줄 추가.
- [x] **T4: 테스트** (AC: 2, 3, 4, 5, 7) — `tests/test_dart_ingest.py`에 추가(신규 파일 아님): fixture `tesstkAcqsDspsSttus` 응답으로 (a) 취득/소각 집계, (b) 총계행 제외 이중집계 방지, (c) 미공시(빈 리스트)→(None,None), (d) 활동0(모든 change_qy=0)→(0,0), (e) `normalize`가 period에 두 필드 채움, (f) `upsert_financial` 재실행 멱등 + buyback None이 기존값 안 덮음. SQLite in-memory·fixture 기반.
### Review Findings (code review 2026-07-10, 자체 8앵글×11검증 + GPT 교차)

자체 리뷰와 GPT가 **핵심 3건(필드별 폴백·실패 격리·이중집계)을 독립적으로 동일 검출** — 교차검증 유효성 입증. GPT는 추가로 null/0 다운스트림 구분·음수 파서·JSON 형태를 잡았고, 자체 리뷰는 호출 순서·내부공백 라벨·문서 KRW 잔존을 잡음.

**Patch (반영)**
- [x] [Review][Patch] **필드별 폴백 비대칭 → 소각 유실** (High, 자체+GPT 일치) — 두 필드 모두 None일 때만 summary 폴백이라, leaf 취득만 파싱되면 총계행의 소각값을 놓쳐 `(취득, None)` → 실제 소각 기업이 워싱 거짓양성. `_buyback_field_total`로 **필드별 독립 판정** 재설계. [dart.py]
- [x] [Review][Patch] **summary 폴백이 총계+합계+소계 전부 합산 → 이중집계** (High, 자체+GPT 일치) — 새 규칙: **총계/합계 = 권위 소스 우선**(유일→그 값, 종류별 파티션→합, 중복 표기 일치→그 값, 상충→null), 총계 없으면 leaf 합, **소계-only는 null**(계층 검증 불가, AC3 "애매하면 null"). [dart.py]
- [x] [Review][Patch] **보조 원천(buyback) 실패가 재무 수집 전체 유실** (High, 자체+GPT 일치) — 쿼터 020 등에서 이미 성공한 company·재무까지 corp 전체 failed 처리(1.8 이전 대비 회귀). buyback 호출을 try/except 격리, `buyback_rows=None`(미상)+`buyback_ok=False` → run.py가 **degraded** 표시(krx cap_ok 패턴). [dart.py, run.py]
- [x] [Review][Patch] **음수 파서 재사용 → 수량 상쇄 조작 가능** (High, GPT; 자체 검증은 기각했으나 방어 비용 1줄) — `_parse_quantity` 신설: 음수(△·괄호)는 수량 도메인에 없음 → None(null>오값). [dart.py]
- [x] [Review][Patch] **scoring의 null≠소각안함 구분 부재** (High, GPT) — washing_flag 소각 항을 `buyback_retired_amount = 0`(**확정 0**)으로 강화, null이면 washing_flag null 전파. `buyback_status`에 **unknown** 추가, purchased_only는 양쪽 확정 시만. 2.1 구현 계약. [scoring.md]
- [x] [Review][Patch] **호출 순서: 빈 accounts에도 buyback 호출 낭비** (Med, 자체) — 호출을 `if accounts:` 안으로 이동(재무 없는 종목당 rate-limit 0.65s+ 절약, 실패 표면 축소). [dart.py]
- [x] [Review][Patch] **JSON 형태 미검증** (Med, GPT) — `_get`에 dict 가드(배열/문자열 응답 → 명확한 DartAdapterError), `_buyback_totals`에 비dict 행 skip. [dart.py]
- [x] [Review][Patch] **내부공백 라벨('총 계') leaf 오분류** (Med, 자체+GPT) — `_norm_label`(전체 공백 제거 후 정확일치). [dart.py]
- [x] [Review][Patch] **README·epics KRW 표기 잔존** (Med, 자체+GPT) — README 84행(수량 명시)·245행(3조→300만 주), epics 1.2/1.8 AC '취득액/소각액'→'수량'. [README.md, epics.md]
- [x] [Review][Patch] **경계 테스트 부재** (Med, 자체+GPT 일치) — 리뷰 회귀 13종 추가(필드별 폴백·상충 총계·종류별 파티션·소계-only·음수·내부공백·malformed·실패 격리·no-accounts skip·include_buyback=False·비dict JSON). [tests/test_dart_ingest.py]
- [x] [Review][Patch] **테스트 hygiene** (Low, 자체) — dead import(_buyback_totals)·미사용 변수(company) 제거.

**Deferred (deferred-work.md 1-8 섹션 기록)**
- [x] [Review][Defer] `"-"` 의미(0 vs 미상) 실응답 확정(High), 취득 목적 분류+처분 활용(High→2.1), 분기 누적/단독 기간 의미(Med), materiality 임계(Med→2.1), 소계-only 손실(Med), buyback_status 세분화(Med→2.1), 요약행 공유 헬퍼(Low), DEV_PLAN 구식 출처(Low).

- [x] **T5(선택, 공통 defer 해소): `_get` ValueError 포착** — `app/ingest/dart.py:_get`이 현재 `requests.RequestException`만 잡아 비JSON 200(`resp.json()` ValueError)이 누출(1-6에서 `dart_ownership._get_json`은 고쳤으나 `dart.py`는 미반영, deferred-work 공통 항목). 새 엔드포인트를 `_get`으로 태우므로 `except (requests.RequestException, ValueError)`로 확장 권장(같은 파일이라 저비용). 반영 시 deferred-work.md 해당 항목 정리.

## Dev Notes

### DART 자기주식 취득·처분 현황 API (조사 결과)

- **엔드포인트**: `GET https://opendart.fss.or.kr/api/tesstkAcqsDspsSttus.json` (DS002 사업보고서 주요정보, apiId 2019006). 2015년 이후 지원.
- **params**: `crtfc_key`, `corp_code`(8자리), `bsns_year`(YYYY, ≥2015), `reprt_code`(11013=1Q/11012=반기/11014=3Q/11011=사업보고서). **재무제표와 완전 동일** → `DartAdapter.fetch`의 기존 인자를 그대로 재사용.
- **응답 `list[]` 필드** (⚠️ **모두 수량(주), 금액 없음**):
  - `acqs_mth1`·`acqs_mth2`·`acqs_mth3` — 취득방법 대/중/소분류(계층 라벨). ⚠️ **총계/소계 요약행 존재 가능** → 이중집계 함정.
  - `stock_knd` — 주식종류(보통주/우선주 등)
  - `bsis_qy` — 기초 수량
  - `change_qy_acqs` — **변동수량 취득** → `buyback_amount` 집계원
  - `change_qy_dsps` — 변동수량 처분(이번 스토리 미사용)
  - `change_qy_incnr` — **변동수량 소각** → `buyback_retired_amount` 집계원 (핵심)
  - `trmend_qy` — 기말 수량
  - `rm`(비고), `stlm_dt`(결산기준일), `rcept_no`, `corp_cls/code/name`
- **수량 문자열**: 콤마 포함(`"1,234,567"`), 회계음수(괄호·△) 가능 → dart.py `_parse_amount` 재사용. `"-"`·`""`·미공시 → None.

### 🚨 핵심 설계 결정 3가지 (dev 착수 전 이해 필수)

1. **AD-3 준수: 별도 어댑터 신설 금지 — `DartAdapter` 확장** — financials의 writer는 정확히 하나(`DartAdapter`)여야 한다(ARCHITECTURE-SPINE AD-3: "각 원천 테이블은 정확히 하나의 소스 어댑터가 소유·기록"). buyback을 `DartBuybackAdapter` 같은 별도 클래스로 만들어 `upsert_financial`을 호출하면 financials **이중 writer**가 되어 AD-3 위반. 따라서 취득/처분 호출을 **기존 `DartAdapter.fetch`에 추가**하고 같은 재무 period에 병합한다. 부수효과: `ingest_financials`가 buyback을 자동으로 함께 수집(run.py 변경·신규 ingest 함수 불필요). 백필은 재무 재수집으로.
2. **수량을 presence-proxy로 저장(액 아님)** — 엔드포인트는 금액을 주지 않는다. 그러나 scoring.md에서 이 두 필드는 오직 `> 0`(불리언 신호)로만 소비된다: `buyback_executed = buyback_amount > 0`, `buyback_retired = buyback_retired_amount > 0`, 실행점수의 자사주 항도 `(buyback_executed ? 1 : 0)`. 즉 **수량이든 액이든 `>0` 판정은 동일** → 수량 합을 그대로 저장해도 다운스트림 정확. 현재 어떤 SQL/뷰도 buyback을 금액으로 쓰지 않음(valuation_metrics는 dividend_total만 사용) → 블라스트 반경 없음. **모델 주석·db-schema를 "수량 신호"로 정정**해 미래 오독(KRW로 계산) 방지. KRW 환산이 필요해지면 별도 스토리(수량×결산일 종가).
3. **이중집계 가드(1-6 재현 방지)** — `acqs_mth1/2/3` 계층에 총계/소계 행이 섞이면 leaf와 합계를 모두 더해 2배가 된다(1-6 "소계 이중가산" High 교훈과 동일 계열). 규칙: 세 분류 컬럼 중 하나라도 `{"총계","소계","합계"}`에 정확일치(strip)하면 요약행으로 보고 **제외**, leaf만 합산. 부분일치 금지(1-6 "특수관계인"의 "계" 오탐 교훈). 실공시 계층 구조는 샘플로 튜닝(raw 미보존이라 재파싱 불가 → 보수적 제외 + null).

### null vs 0 구분 (AC4 핵심)

| 상황 | `_buyback_totals` 반환 | 저장 결과 | 의미 |
|---|---|---|---|
| 미공시(status 013/빈 리스트) | `(None, None)` | upsert None-skip → 기존값 보존 | unknown(모름) |
| 공시 있음, 모든 change_qy=0 | `(0, 0)` | 0 저장 | known: 이번 기간 취득/소각 없음 → `>0`=False |
| 공시 있으나 전부 파싱 실패 | `(None, None)` | 기존값 보존 | unknown |
| 취득 3M주·소각 0 | `(3000000, 0)` | 저장 | executed=True, retired=False (전형적 워싱 후보) |

> `upsert_financial`은 None 필드를 건너뛰므로(app/repositories/financials.py:50) "미공시"는 기존 non-null을 지우지 않는다. "활동 0"은 **정수 0으로 저장해야** `buyback_executed=False`가 성립 — `None`으로 뭉개면 안 됨.

### 재사용 (재발명 금지 — 기존 코드에서 가져올 것)

| 필요 | 기존 위치 | 재사용 방법 |
|---|---|---|
| HTTP GET + JSON status(000/013) 처리 | `app/ingest/dart.py:_get` (line 165-187) | 그대로 사용. `allow_no_data=True`로 013을 `{"list": []}`로. **신규 엔드포인트도 `_get` 경유**(별도 세션·limiter 만들지 말 것 — 인스턴스 것 재사용). |
| 수량 파싱(콤마·회계음수→int, "-"·""→None) | `app/ingest/dart.py:_parse_amount` | `change_qy_acqs`·`change_qy_incnr`에 그대로. |
| 키 미노출 예외 | `app/ingest/dart.py:DartAdapterError` | 재사용. 예외/로그에 crtfc_key·URL 금지. |
| 멱등 upsert(None-safe, buyback 필드 포함) | `app/repositories/financials.py:upsert_financial` (line 45-51에 `buyback_amount`·`buyback_retired_amount` 이미 포함) | **변경 불필요** — 이미 두 필드를 None-safe로 갱신. |
| 종목별 커밋 + 실패목록, fetch는 txn 밖 | `app/ingest/run.py:ingest_financials` | **변경 불필요** — buyback이 fetch에 편승. |
| fixture 기반 테스트 | `tests/test_dart_ingest.py` | 동일 파일에 tesstkAcqsDspsSttus fixture 추가. |
| 형제 패턴(구조화 JSON 집계·요약행 제외) | `app/ingest/dart_ownership.py:_treasury_stock_pct`, `_is_summary` | 요약행 제외·null>오값 로직 참고(단 여기선 합계행 사용이 아니라 leaf 합산). |

### 아키텍처 제약

- **AD-3**: `DartAdapter`가 financials의 **유일** writer. buyback도 이 어댑터가 씀(별도 writer 금지). `source="dart"`.
- **AD-5**: corp_code(8자리) FK·정식 키.
- **AD-7**: 멱등 upsert 자연키 `(corp_code, year, quarter)`. buyback은 기존 재무 행에 병합.
- **AD-2**: 수집은 서빙과 분리. repository upsert만, 라우터/서비스 없음(buyback은 2.1 gap_engine이 financials에서 직접 읽음).
- **NFR2**: 미공시·파싱 실패 시 null 허용, 수집 실패 금지.
- **NFR3 무관**: 임계치·가중치 스토리 아님(수집만).

### 데이터 모델 (financials — 변경 없음, 주석만 정정)

`app/models.py:76-77` (마이그레이션 불필요):
- `buyback_amount: Mapped[int | None]` BigInteger — 주석 "자사주 매입액" → **"자사주 취득 수량(주) — 워싱 presence 신호(>0), 액 아님"**
- `buyback_retired_amount: Mapped[int | None]` BigInteger — 주석 "소각액" → **"자사주 소각 수량(주) — 워싱 presence 신호(>0), 액 아님"**

### 소스 트리 (이 스토리)

```
app/
  ingest/dart.py        # UPDATE: fetch에 tesstkAcqsDspsSttus 호출 + normalize에서 _buyback_totals 집계 + _get ValueError 포착(T5)
  models.py             # UPDATE: buyback 필드 2개 주석만 정정(수량 신호). 마이그레이션 없음.
tests/test_dart_ingest.py   # UPDATE: tesstkAcqsDspsSttus fixture·집계·이중집계·null/0·멱등 테스트
docs/specs/spec-valueup-washing/db-schema.md   # UPDATE: buyback 필드 "수량 신호" 각주
```

**변경 없음(중요)**: `run.py`(buyback이 ingest_financials에 편승), `repositories/financials.py`(upsert_financial이 이미 두 필드 처리), alembic(신규 리비전 없음).

### 테스트 표준

- 라이브 키 없이 **fixture 기반 단위 테스트**. `_buyback_totals`는 **순수 함수** → rows 직접 주입(네트워크 없음). SQLite in-memory.
- 필수 케이스: (a) 취득·소각 leaf 합산, (b) 총계행 포함 시 제외해 이중집계 방지, (c) 빈 리스트→(None,None), (d) 모든 change_qy=0→(0,0), (e) `normalize`가 period 두 필드 채움(fetch 반환 dict 직접 주입), (f) `upsert_financial` 멱등 + buyback None이 기존값 보존, (g) `DART_API_KEY` 미설정→`DartAdapterError`.
- 실행: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -q`. **기존 78 passed 회귀 0** 확인.

### Previous Story Intelligence (1.2 DART, 1.6 지분구조)

- **1.6이 이 스토리를 예고**(known-limitations line 131): "정밀 자사주 취득/소각 이력은 tesstkAcqsDspsSttus 별도 — 2.1 워싱 buyback 연계는 후속". 이제 그 후속.
- **이중집계 함정은 1.6에서 실제 발생**(소계 이중가산 High patch) → 요약행 정확일치 제외로 해결. 여기서도 `acqs_mth` 계층에 동일 적용.
- **부분일치 금지**(1.6 "특수관계인"의 "계" 오탐, 테스트가 검출) → 요약행 판정은 strip 완전일치.
- **방어적 매칭**(1.2 total_debt 중복 라벨 교훈): 회사마다 행 구성이 다름 → 애매하면 null.
- **키 redaction**: 예외·로그에 crtfc_key/URL 미포함(1.2 GPT High).
- **부분성공 정책**: 한 종목 실패가 배치를 안 막음(`IngestResult.failed`) — 기존 `ingest_financials` 그대로.
- **콘솔 인코딩**: 한글 다수 → `PYTHONIOENCODING=utf-8`(cp949 표시깨짐은 데이터 정상).
- **공통 deferred**(중복 지적 금지): 동시성 on_conflict(v1 단일프로세스라 보류), 원천 감사메타(ingested_at, 전 원천 공통 후속).

### 알려진 한계 / 스코프 경계 (v1)

- **수량 = 액 프록시**: buyback 필드는 KRW가 아니라 수량(주). `>0` 신호로만 사용(scoring.md 정합). KRW 정밀액이 필요하면 후속(수량×결산일 종가). **모델/db-schema 주석으로 명시**해 오독 방지.
- **이중집계는 보수적 제외로 근사**: 실공시 `acqs_mth` 계층 샘플 없이 총계/소계/합계 정확일치 제외. raw 미보존이라 재파싱 불가 → 계층 구조 확인 후 튜닝(deferred). 애매하면 null.
- **buyback만 있고 accounts 없는 종목**: 재무 period가 안 생겨 buyback 미적재(드묾). 필요 시 period 생성 조건 완화는 후속.
- **분기/사업보고서 중복**: 같은 연도의 분기·사업보고서가 각각 다른 quarter로 적재(재무제표와 동일 자연키 `(corp_code, year, quarter)`) — 재무제표 패턴 그대로라 신규 충돌 없음.
- **소각 vs 이익소각**: `change_qy_incnr`이 소각 수량을 통합 제공 → 워싱 판정엔 충분. 소각 사유(이익소각/자본감소) 세분은 미수집.

### 착수 전 리드 확인 요망 (SAVE QUESTIONS)

1. **수량 presence-proxy 수용 확정** — 엔드포인트가 금액을 안 줘서 `buyback_amount`/`buyback_retired_amount`에 **수량(주)**을 넣는다(‘>0’ 신호로만 쓰여 다운스트림 정확). 이전에 "financials 재사용"을 고른 시점엔 이 필드가 '액'인 줄 알았을 수 있어 재확인. 대안: (B) `buyback_qty`/`buyback_retired_qty` 신규 컬럼(마이그레이션 0008, 의미 정직) + scoring.md·2.1 AC를 qty 참조로 수정. **권장=현행 재사용(A)**: 무마이그레이션·spec의 `>0` 로직 무변경.
2. **T5(`_get` ValueError 포착) 이번에 포함할지** — 공통 defer 해소 저비용이나 스코프 밖이면 분리 가능.

### 스택

FastAPI 0.139.0 / SQLAlchemy 2.0.51 / PostgreSQL 17(개발 SQLite) / alembic / requests. Python 3.12. **신규 의존성·마이그레이션 없음**(기존 필드·어댑터 확장).

### References

- [Source: epics.md#Story-1.8] — AC 원본(2026-07-10 추가), 배경
- [Source: scoring.md#자사주-3단계] — buyback_executed/retired/status가 `>0`로만 소비, washing_flag의 `NOT buyback_retired`
- [Source: db-schema.md#financials] — buyback_amount·buyback_retired_amount 컬럼(BigInteger)
- [Source: ARCHITECTURE-SPINE.md#AD-3,5,7] — financials 단일 writer(dart_adapter)·corp_code 키·멱등 upsert(corp_code+year+quarter)
- [Source: 1-2-ingest-financials-dart.md] — DartAdapter fetch/normalize/upsert, `_get`(013)·`_parse_amount`·`_RateLimiter`·키 redaction·per-corp 커밋·fixture
- [Source: 1-6-ingest-ownership.md] — 요약행 제외 이중집계 방지·부분일치 금지·null>오값(형제 패턴), line 131 예고
- [Source: deferred-work.md] — 감가상각비/자사주 데이터 공백, `_get` ValueError 공통 defer
- OpenDART 자기주식 취득 및 처분 현황(tesstkAcqsDspsSttus) DS002 apiId 2019006: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS002&apiId=2019006

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (bmad-dev-story)

### Debug Log References

- **AD-3 준수 확장**: 별도 어댑터 신설 없이 `DartAdapter.fetch`에 `tesstkAcqsDspsSttus.json` 호출 추가(`include_buyback=True`, 기존 `_get`·`allow_no_data=True` 재사용). financials 단일 writer 유지. `ingest_financials`(run.py)·`upsert_financial`(repo)·alembic 무변경 — buyback이 재무 수집에 편승.
- **`_buyback_totals` 순수 함수**: 요약행(`acqs_mth1/2/3` 중 하나라도 총계/소계/합계 정확일치) 제외한 leaf 행에서 `change_qy_acqs`·`change_qy_incnr`를 `_parse_amount`로 합산. leaf 데이터 전무 시 요약행 폴백(총계만 오는 응답 손실 방지). 필드별 파싱값 없으면 None(미공시), "0"은 0(활동 없음) → 미공시/활동0 구분(NFR2).
- **수량 presence-proxy(액 아님)**: 엔드포인트가 금액 미제공. scoring이 `>0`로만 소비 → 수량 저장으로 다운스트림 정확. models.py·db-schema.md 주석 정정으로 오독 방지.
- **이중집계 가드**: 총계행 포함 fixture로 3M(leaf) vs 6M(이중가산) 구분 테스트. 부분일치 금지(1.6 "계" 오탐 교훈) → strip 완전일치.
- **T5**: `_get` except를 `(RequestException, ValueError)`로 확장 — 비JSON 200(resp.json ValueError) 누출 해소(deferred-work 공통 항목). 키 미노출 유지 확인 테스트.

### Completion Notes List

- **리드 확인 2건**: (1) 수량 presence-proxy = **권장안 A 채택**(무마이그레이션·spec `>0` 로직 무변경). (2) T5 = **포함**(같은 파일 저비용, 공통 defer 해소).
- **검증**: pytest **87 passed**(buyback 9 신규 + 기존 78 회귀 0), 라이브 키 없이 fixture 기반. 경고 2건은 기존 cp949(alembic subprocess)·Starlette deprecation(내 변경 무관).
- **마이그레이션 없음**: `buyback_amount`·`buyback_retired_amount` 컬럼 기존 존재(0002), `upsert_financial`이 이미 두 필드 None-safe 처리.
- **스코프 한계**(deferred): 수량=액 프록시(KRW 정밀액은 수량×종가 후속), acqs_mth 계층 이중집계는 실공시 샘플로 튜닝(raw 미보존), buyback만 있고 accounts 없는 종목은 period 미생성(드묾).

### File List

- `app/ingest/dart.py` (UPDATE: fetch에 tesstkAcqsDspsSttus 호출+include_buyback+실패 격리(buyback_ok), normalize buyback 집계, `_buyback_field_total`·`_buyback_totals`·`_buyback_row_kind`·`_norm_label`·`_parse_quantity` 헬퍼, `_get` ValueError 포착+dict 가드)
- `app/ingest/run.py` (UPDATE: ingest_financials가 buyback_ok=False를 degraded로 표시)
- `app/models.py` (UPDATE: buyback 필드 2개 주석 정정 — 수량 신호. 마이그레이션 없음)
- `tests/test_dart_ingest.py` (UPDATE: buyback 테스트 22종 — 구현 9 + 리뷰 회귀 13)
- `docs/specs/spec-valueup-washing/db-schema.md` (UPDATE: buyback 필드 "수량 신호" 각주)
- `docs/specs/spec-valueup-washing/scoring.md` (UPDATE: washing 소각 항 '확정 0' 조건, buyback_status unknown 추가 — 2.1 계약)
- `README.md` (UPDATE: buyback 수량 표기·예시값 정정)
- `docs/planning-artifacts/epics.md` (UPDATE: 1.2/1.8/2.1 AC buyback 수량 표기)
- `docs/implementation-artifacts/deferred-work.md` (UPDATE: 1-8 리뷰 defer 8건)

## Change Log

- 2026-07-10: Story 1.8 컨텍스트 생성(bmad-create-story) — 자기주식 취득·처분 현황(DART tesstkAcqsDspsSttus) 수집으로 financials.buyback_amount·buyback_retired_amount 채움(구조적 100% null 해소). AD-3 준수 위해 별도 어댑터 대신 `DartAdapter` 확장(financials 단일 writer), 무마이그레이션(기존 필드 재사용). 핵심 발견: 엔드포인트가 수량만 제공 → scoring이 `>0`로만 소비하므로 수량을 presence-proxy로 저장. 이중집계 가드(1-6 교훈). Status: ready-for-dev. **리드 확인 요망 2건(수량 프록시 수용·T5 포함 여부)**.
- 2026-07-10: Story 1.8 구현(bmad-dev-story) — `DartAdapter` 확장(tesstkAcqsDspsSttus 호출·`_buyback_totals` 집계·요약행 제외 이중집계 방지·미공시/활동0 구분), 모델·db-schema 주석 정정(수량 신호), `_get` ValueError 포착(T5). 리드 확인 2건 권장안(수량 프록시 A·T5 포함) 반영. **pytest 87 passed**(buyback 9 신규, 회귀 0). 무마이그레이션. Status → review.
- 2026-07-10: 코드리뷰(자체 8앵글×11검증 + GPT 교차, verbatim 번들) — **Patch 11건 반영**: `_buyback_totals`를 필드별 독립+총계 권위(유일/파티션/일치)+상충·소계-only null로 재설계(High×2), buyback 실패 격리→degraded(High, 재무 유실 회귀 해소), `_parse_quantity` 음수 거부(High), scoring.md washing '확정 0' 조건+buyback_status unknown(High), 호출을 `if accounts:` 안으로(Med), `_get` dict 가드(Med), `_norm_label` 내부공백(Med), README·epics 수량 표기(Med), 리뷰 회귀 테스트 13종+hygiene. 핵심 3건은 자체·GPT 독립 동일 검출. Defer 8건 기록. **pytest 100 passed**(회귀 0). Status → done. **Epic 1 재완료.**
