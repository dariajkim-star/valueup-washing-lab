---
baseline_commit: 4ca4e2b785090604702c87c3a891958f70ff67b7
---

# Story 3.5: Tableau 대시보드 연계

Status: done

## Story

As a 애널리스트,
I want Tableau에서 시장·매크로 대시보드를 보는 것,
So that 발표·리포트용 시각 자료를 얻는다.

## Acceptance Criteria (epics.md 원문)

**Given** `/stats/*`와 지표·스코어·매크로 데이터(UX-DR5)
**When** Tableau를 PostgreSQL에 연결하면
**Then** 밸류업 점수·업종별 저평가 맵·ROE-PBR 산점도·배당/자사주 4개 뷰와 ECOS 매크로 레이어가 구성되고
**And** 각 뷰가 API/DB 뷰를 소스로 갱신된다.

UX-DR5: Tableau 4개 뷰 + 매크로 레이어 — 밸류업 점수·업종 저평가 맵·ROE-PBR 산점도·배당/자사주 + ECOS 금리/환율 컨텍스트.

## ⚠️ 스토리 오너 결정 필요 사항 — AC와 실제 스택의 불일치 (dev 착수 전 필독)

에픽 AC는 **"Tableau를 PostgreSQL에 연결"**이라고 쓰여 있으나, 실측 결과 프로젝트의 실제 DB는 **SQLite**다:

- `app/config.py:34` — `database_url: SecretStr = SecretStr("sqlite:///./valueup.db")`
- `app/db.py:18` — sqlite 백엔드 분기 존재. PostgreSQL 마이그레이션은 어디에도 없음.
- 메모리·로드맵상 배포 타깃은 **Tableau Public**(무료)인데, Tableau Public은 라이브 DB 연결(PostgreSQL 포함)을 **지원하지 않는다** — 파일(CSV/Excel/Hyper extract)·Google Sheets 등 정적 소스만 가능.

**권장 해법(비용 최소·AC 정신 보존): CSV export 레이어.**
PostgreSQL 마이그레이션(과잉·다른 스토리 전부 재검증 필요)이나 유료 Tableau Desktop+ODBC 대신, DB 뷰/테이블에서 **뷰별 tidy CSV를 뽑는 export 스크립트**를 만들고 Tableau는 그 CSV를 소스로 쓴다. "각 뷰가 API/DB 뷰를 소스로 갱신된다"는 AC의 And절은 "export 스크립트 재실행 → CSV 갱신 → Tableau 새로고침"으로 충족(소스가 DB 뷰인 것은 동일, 전달 매체만 파일). AC의 "PostgreSQL에 연결하면" 문구는 이 스토리에서 **의도적 일탈**로 기록하고 근거를 남길 것 — 1.2/1.3/1.5(credit lab)와 같은 "스토리오너 재량 결정 + 근거 문서화" 패턴.

**Tableau 워크북 자체는 GUI 산출물**이라 AI가 코드로 완성할 수 없다. 이 스토리의 dev 산출물은 ①export 스크립트+CSV ②뷰별 구성 스펙 문서(필드·차트타입·필터·색상 규칙) ③검증 테스트까지이고, Tableau Public에서 워크북을 실제로 조립·게시하는 것은 사용자 수작업(스펙 문서가 그 가이드)이다. 이 분업을 Completion Notes에 명시할 것.

## Dev 구현 가이드

### 산출물 1 — Export 스크립트: `pipelines/export_tableau.py` (NEW)

CLI로 실행하면 `exports/tableau/`(gitignore 추가)에 뷰별 CSV 4~5개를 쓴다. **AD-2 준수: SQL 직접 접근 금지 — repository 레이어를 통해 조회**하거나, 불가피하면 이 스크립트를 "수집·배치 레이어"(ingest 계열과 동급)로 규정하고 read-only SELECT만 수행함을 문서화(AD-3/AD-4/AD-10의 writer 제약과 무관한 읽기 전용 경로임을 명시). 어느 쪽이든 근거를 스토리에 기록.

뷰별 CSV 스키마(tidy, 1행=1관측):

1. **`valueup_scores.csv`** (밸류업 점수 뷰): corp_code, corp_name, market, sector, as_of, execution_score, achievement_rate, progress_rate, washing_flag, buyback_status — `valueup_score` ⋈ `company`
2. **`sector_valuation_map.csv`** (업종별 저평가 맵): sector, market, corp_code, corp_name, pbr, per, ev_ebitda, mna_target_score, valuation_score — `valuation_metrics`(최신 year/quarter) ⋈ `company` ⋈ `mna_score`. 업종별 트리맵/히트맵용
3. **`roe_pbr_scatter.csv`** (ROE-PBR 산점도): corp_code, corp_name, market, sector, roe, pbr, execution_score(색), washing_flag(모양), market_cap 대용 없음 주의 — `valuation_metrics` 최신 행 ⋈ `company` ⋈ `valueup_score`
4. **`dividend_buyback.csv`** (배당/자사주): corp_code, corp_name, sector, year, payout_ratio, dividend_total(financials에서), buyback_executed, buyback_retired, buyback_status — `financials`+`valuation_metrics` ⋈ `valueup_score`
5. **`macro_layer.csv`** (ECOS 매크로 레이어): indicator, date, value, frequency — `macro_indicator` 전체(3,369행 실측)

**null 정직성 계약(이 프로젝트 1.8부터의 핵심 원칙)**: null은 빈 셀로 내보내고 0으로 채우지 말 것. 3.4 리뷰에서 "0 falsy → '—' 세탁"이 High로 잡혔던 프로젝트다 — export에서 null→0 세탁이 나오면 같은 계열의 반려 사유.

### 산출물 2 — 뷰 구성 스펙 문서: `docs/implementation-artifacts/tableau-spec-3-5.md` (NEW)

4개 뷰+매크로 레이어 각각에 대해: 소스 CSV, 차트 타입, 행/열 선반 필드, 색/크기/모양 인코딩, 필터(시장·업종·워싱), null 표시 규칙(3.2 Figma에서 확정한 null 시각언어와 일관), 대시보드 배치. 사용자가 Tableau Public에서 그대로 조립할 수 있는 수준으로.

### 산출물 3 — 검증

- pytest: export 함수 단위 테스트(합성 DB로 스키마·null 보존·최신 as_of 선택 검증). 기존 231 passed 회귀 0 유지.
- 실데이터 실행: `valueup.db`(valueup_score 26·mna_score 31·valuation_metrics 66·macro 3,369행 실측)로 CSV 생성 후, 대표 수치가 `/stats/*` API 응답과 일치하는지 대조(예: washing_ratio를 CSV에서 재계산 → `/stats/summary`와 비교). **API-CSV 패리티가 "각 뷰가 API/DB 뷰를 소스로 갱신된다" AC의 실증**이다.

### 아키텍처 가드레일

- AD-1: 파생지표는 `valuation_metrics` VIEW에서만 — export가 지표를 재계산하지 말 것(뷰를 SELECT).
- AD-2: 레이어 의존 단방향. export 스크립트는 routers를 import하지 말 것.
- AD-4/AD-10: valueup_score·mna_score는 읽기 전용.
- AD-8: as_of 신선도 — 스코어 계열은 최신 as_of 행만 exports에 포함하고, 어느 as_of인지 CSV에 컬럼으로 남길 것(3.4의 as_of 시점 혼합 High 리뷰와 같은 함정: **뷰별 CSV가 서로 다른 기준일로 뽑히면 대시보드에서 시점이 섞인다** — 단일 as_of로 수렴시키고 스크립트 로그에 명시).

### 이전 스토리 인텔리전스 (3-1, 3-4)

- 3-1이 만든 `/stats/market-comparison`·`/stats/summary`·`/stats/macro`가 "Tableau가 물릴 집계 JSON"으로 이미 설계됨 — export 검증의 대조 기준으로 활용.
- 3-4 리뷰 교훈 3종이 이 스토리에 그대로 적용: ①as_of 혼합 금지 ②null≠0 세탁 금지 ③에러를 빈 데이터로 세탁 금지(export 실패 시 빈 CSV를 쓰지 말고 명시적 에러).
- 3-3/3-4에서 corp_code는 `^\d{8}$` 패턴이 계약.
- 프로젝트 관례: 구현 → status=review → **GPT 교차리뷰**(코드 verbatim 전달, 축약 금지 — epic-1 액션아이템) → 반영 → done.

### 관련 테이블 실측 스키마 (2026-07-14, valueup.db)

- `company(corp_code, stock_code, corp_name, market, sector)`
- `valuation_metrics(corp_code, year, quarter, roe, roa, pbr, per, ev_ebitda, debt_ratio, payout_ratio, net_cash, ebitda_margin, yoy_revenue_growth, yoy_income_growth)` — VIEW, 66행
- `valueup_score(…, as_of, achievement_rate, progress_rate, execution_score, washing_flag, buyback_executed, buyback_retired, buyback_status, target_roe, actual_roe, roe_gap)` — 26행
- `mna_score(…, as_of, mna_target_score, valuation_score, capacity_score, ownership_score, macro_score, population_basis)` — 31행
- `macro_indicator(indicator, date, value, frequency)` — 3,369행

## Dev Agent Record

### Agent Model Used

claude-fable-5 (bmad-create-story + bmad-dev-story, 2026-07-14)

### Debug Log References

- 스크립트 위치를 스토리 가이드의 `pipelines/export_tableau.py`에서 `app/export/tableau.py`로 변경 — 이 repo에 pipelines/ 디렉터리가 없고(credit lab 관례가 스토리에 새어 들어간 것), ingest와 동급의 배치 레이어로 app/ 안에 두는 것이 기존 구조와 정합. SQL은 전부 신규 `app/repositories/export.py` 경유(AD-2).
- look-ahead 부분 차단 규칙(`year<yr OR (year=yr AND quarter<4)`)을 screening/stats와 동일하게 적용 — 규칙이 갈라지면 CSV-API 패리티가 깨지므로 5번째 사용처로 독립 작성(공통화는 deferred-work 기존 항목 유지).
- CSV는 UTF-8 BOM(한글 종목명 Tableau/Excel 호환), bool은 소문자 통일, None은 csv 모듈 기본으로 빈 셀.

### Completion Notes List

- **산출물 3종 완료**: ① `app/export/tableau.py`(CLI: `python -m app.export.tableau`) + `app/repositories/export.py` — 뷰별 tidy CSV 5개 생성 ② `docs/implementation-artifacts/tableau-spec-3-5.md` — 뷰별 차트타입·선반·인코딩·필터·null 규칙·대시보드 배치·게시 절차 ③ 테스트 6종.
- **계약 3종을 테스트로 고정**: 단일 as_of 수렴(구 as_of 행 미혼입 실증), null→빈 셀 + 정상값 0 보존(3.4 High 회귀 방지), 빈 스코어 시 NoScoreDataError(파일 0개 — 빈 CSV 세탁 금지). + look-ahead 배제·mna 부재 정직 노출·매크로 결측.
- **실데이터 실행(valueup.db)**: as_of=2026-07-13, valueup_scores 26행·sector_valuation_map 33행·roe_pbr_scatter 31행·dividend_buyback 66행·macro_layer 3,369행.
- **API-CSV 패리티 실증(AC "각 뷰가 API/DB 뷰를 소스로 갱신" 검증)**: `/stats/summary` — as_of·판정모수 19·워싱 0·washing_ratio 0.0이 CSV 재계산과 일치. `/stats/macro` — 최신값 4종(base_rate 2.5, bond_3y 3.768, usd_krw 1504.2, leading_index 104.8) 전부 CSV와 일치.
- pytest **237 passed**(기존 231 + 신규 6, 회귀 0).
- **AC "PostgreSQL 연결" 의도적 일탈**: Tableau Public은 라이브 DB 연결 미지원 + 실스택 SQLite — CSV export 레이어로 대체(스토리 상단 결정 사항 참조). Tableau 워크북 조립·게시는 GUI 수작업(spec 문서가 가이드) — dev 산출물 범위 밖.
- 알려진 한계: sector가 DART induty 코드 그대로(API와 동일) — 표시용 업종명 매핑은 스코프 밖, Tableau 별칭으로 수동 처리 가능(spec에 기재).

### File List

- `app/repositories/export.py` (NEW: 뷰별 read-only 조회 5종)
- `app/export/__init__.py`·`app/export/tableau.py` (NEW: CSV export CLI)
- `tests/test_export_tableau.py` (NEW: 6 tests)
- `docs/implementation-artifacts/tableau-spec-3-5.md` (NEW: Tableau 조립 스펙)
- `.gitignore` (UPDATE: exports/ 제외)
- `exports/tableau/*.csv` (생성물, gitignore — 재생성 가능)

### Review Findings (code review 2026-07-14, GPT — High 3·Med 4·Low 1, patch 7/리드결정 1)

- [x] [Patch][High] **latest_as_of가 두 엔진 공존 기준일을 보장 안 함** — screening의 max(v,m)를 그대로 써서, 한 엔진만 최신이면 다른 쪽 CSV가 통째로 0행인 채 "완료" 로그가 나올 수 있었음. `latest_common_as_of`(교집합 max) 신설, 교집합 없으면 NoScoreDataError. 테스트 2종(valueup만 최신 → 공통일 선택 / mna 전무 → 거부).
- [x] [Patch][High] **5개 CSV 기록 비원자성** — 세 번째 파일 실패 시 신·구 세대가 섞인 디렉터리가 남았음. staging 디렉터리에 5개+**manifest.json**(as_of·generated_at·행수) 전부 성공 시에만 교체, 실패 시 staging 폐기·기존 스냅숏 무손상. 부분 실패 보존 테스트(monkeypatch로 3번째 실패 유발 → 바이트 단위 불변 확인).
- [x] [Patch][High] **현재 buyback_status를 과거 전 연도에 반복** — 2026 스냅숏 상태(retired)가 2023 행에도 칠해져 "그때도 소각했다"로 오독. `period_buyback_status(amount, retired_amount)` 순수함수로 **그 연도 원천에서 계산**(retired/purchased_only/none/무관측 null), ValueupScore 조인 제거. 실데이터 실증: 고려아연 2023=purchased_only(스냅숏은 retired). 스펙 문서도 시계열 색상 소스를 이 컬럼으로 교체.
- [x] [Patch][Med] **dividend_buyback에 market 부재** — 전역 시장 필터 불가였음. Company.market 조인+컬럼 추가+테스트.
- [x] [Patch][Med] **_write_csv가 누락 키를 빈 셀로 세탁** — extrasaction="raise"는 추가 키만 잡음. row 키 집합 == 스키마 직접 검사, 불일치 시 ExportSchemaError(missing/extra 명시)+테스트.
- [x] [Patch][Med] **CSV의 null 정직성이 Tableau에서 다시 숨겨짐** — 트리맵 크기 null 종목은 화면에서 통째로 사라짐. 스펙 문서에 "미산정 KPI 시트"를 **필수**로 격상(산출 N/미산정 M + 종목 목록, 산점도 좌표 결측 포함), 검증 기준에 "산출+미산정=manifest 행수" 추가.
- [x] [Patch][Low] **Tableau 타입 추론 위험** — corp_code `00155319`→`155319` 소실. 스펙에 필드별 타입 강제 표(String/Date/Whole Number) 신설, 테스트 시드를 실데이터형 숫자 코드 sector로 교체해 문자열 보존 검증. 조립 후 검증 기준에 선행 0 확인 추가.
- [x] [Patch][스펙 추가지적] **buyback_amount+retired 합산 금지·단위 분리** — 소각량이 취득량 부분집합이면 중복 계산 + 금액(KRW) vs 수량(주) 혼합. 스펙에서 별도 라인·축 제목 분리로 수정.
- [x] [리드 승인 완료][Med] **AC 일탈의 공식 승인** — 2026-07-14 리드 승인("진행시켜"). epics.md 3.5 AC를 CSV 스냅숏 연결 기반으로 개정(개정 주석에 근거·일자·승인 명시). 구현이 개정 AC를 충족함은 2차 검증에서 실증됨.

### 2차 검증 (리뷰 반영 후)

- pytest **242 passed**(신규 5: 공통 as_of 2종·원자성·스키마 강제·기간별 상태 단위테스트, 회귀 0).
- 실데이터 재실행: 교집합 as_of=2026-07-13(두 엔진 공존 확인), manifest.json 생성(5뷰 행수 기록), dividend_buyback에 market·period_buyback_status 컬럼 실증.

## Change Log

- 2026-07-14: Story 3.5 생성 — AC의 "PostgreSQL 연결"과 실제 스택(SQLite+Tableau Public) 불일치 발견, CSV export 레이어로 해소하는 방향 제시(스토리오너 결정 필요 표기). 산출물 3종(export 스크립트·뷰 스펙 문서·API-CSV 패리티 검증) 정의.
- 2026-07-14: Story 3.5 구현 — export 레이어(repository+CLI)·테스트 6종·Tableau 스펙 문서. 실데이터 5개 CSV 생성 + /stats/* 패리티 실증. 237 passed. Status → review(GPT 교차리뷰 대기).
- 2026-07-14(post-done 보완, 셀프리뷰 4건): ①공통일보다 최신인 엔진 실행분이 있으면 WARNING(조용한 과거 후퇴 방지 — `engine_latest_as_of`) ②`--as-of` CLI(과거 스냅숏 재현, 두 엔진 실재 검증) ③스냅숏 교체를 rmtree→rename에서 **.old 대피 후 rename**으로 변경(어느 시점 크래시에도 완전한 스냅숏 최소 1개 보존, 실패 시 .old 원위치 복구) ④뷰 간 중복 쿼리 제거(metrics/companies를 export_all에서 1회 조회해 주입, 미주입 시 자체 조회 호환). 테스트 +4, 246 passed.
- 2026-07-14: **GPT 리뷰**(Changes Requested, High3·Med4·Low1) triage·반영 — 교집합 as_of·원자적 스냅숏+manifest·기간별 자사주 상태(3 High 전부 patch), market 컬럼·스키마 강제·null 가시성 시트 필수화·타입 강제 표·축 단위 분리 patch. 242 passed. 잔여 1건: AC 개정 리드 승인 대기.
- 2026-07-14: AC 개정 리드 승인 → epics.md 3.5 AC를 CSV 스냅숏 연결로 공식 개정(개정 주석 포함). 전 리뷰 항목 해소 — Status → done.
