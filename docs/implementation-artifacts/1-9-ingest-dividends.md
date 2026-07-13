---
baseline_commit: 08a43c8
---

# Story 1.9: 배당총액 수집 (DART 배당에 관한 사항)

Status: done

## Story

As a 애널리스트,
I want DART "배당에 관한 사항"(`alotMatter`)의 현금배당금총액이 `financials.dividend_total`에 채워지는 것,
so that 실행점수(2.1)의 배당 항(0.2 가중)과 뷰 payout_ratio가 실데이터로 계산된다(리허설 발견 1: 현재 구조적 100% null → execution_score 전 종목 0%).

## 배경

드레스 리허설(2026-07-13)에서 `dividend_total`이 66행 전부 null임을 확인 — 1.2가 "별도공시 best-effort"로 남긴 채 수집 경로가 구현된 적 없음(**1-8 buyback과 동일한 병**). 정밀 출처는 DART `alotMatter.json`(DS002 배당에 관한 사항, params=crtfc_key·corp_code·bsns_year·reprt_code — 재무제표와 동일). 응답 `list[]`의 `se`(구분) 중 **"현금배당금총액(백만원)"** 행의 `thstrm`(당기)이 배당총액, **단위 백만원 → ×1,000,000 스케일 필수**.

## Acceptance Criteria

1. **Given** `DartAdapter`(financials 유일 writer, AD-3), **When** fetch하면, **Then** 재무 period 생성 시 `alotMatter.json`도 호출한다(1.8과 동일: `if accounts:` 내부·격리 try/except·실패 시 `dividend_ok=False`로 재무 수집은 계속).
2. **Given** 응답 rows, **Then** `dividend_total = se가 "현금배당금총액(백만원)"인 행의 thstrm × 1_000_000`(KRW). 라벨 정확일치(strip, 1-6 교훈), 음수·파싱불가·행 없음 → null(NFR2).
3. **Given** 미공시(013)와 실패, **Then** 미공시=[]→null(기존값 보존), 실패=None→null+degraded(run.py buyback_ok 패턴 미러).
4. **Given** 재실행, **Then** `upsert_financial` None-safe로 멱등(변경 불필요 — dividend_total 이미 필드 목록에 있음).
5. **Given** fixture 테스트, **Then** 스케일·라벨 정확일치·null 구분·normalize 병합이 검증되고 기존 158 회귀 0.

## Tasks / Subtasks

- [x] **T1**: `dart.py` fetch에 alotMatter 호출(1.8 buyback 블록 미러: 격리·dividend_ok) + `_dividend_total(rows)` 헬퍼(라벨 정확일치+백만원 스케일+음수 방어).
- [x] **T2**: normalize에서 `rec["dividend_total"] = _dividend_total(period.get("dividend_rows"))`로 교체(passthrough 제거), fixture(DART_RAW_SAMSUNG)를 dividend_rows 기반으로 갱신.
- [x] **T3**: run.py `dividend_ok` degraded 반영(buyback_ok와 동일 라인).
- [x] **T4**: 테스트 — 스케일(361백만→3.61억), 라벨 변형 미매칭→null, 음수→null, 미공시 vs 실패, 회귀 0.

## Dev Notes

- **재사용**: 1.8 buyback 블록이 정확한 템플릿(격리 try/except·ok 플래그·`if accounts:` 내부·rows None/[] 구분). `_parse_amount` 재사용. upsert·run.py 구조 변경 없음(플래그 한 줄).
- **단위 함정이 이 스토리의 핵심 리스크**: buyback은 수량이라 스케일 없었지만 배당은 **백만원 단위** — 스케일 누락 시 100만 배 축소된 값이 조용히 payout_ratio를 오염. 라벨의 "(백만원)"을 파싱 근거로 삼고, 단위 미확인 라벨은 null(값을 만들지 않음).
- **주당배당금·배당성향 행은 미사용**(총액만). 주식배당은 현금 아님 — "현금배당금총액"만.
- 종목당 호출 3→4로 증가(쿼터 영향은 1.8 리뷰에서 이미 문서화된 계열).

### Review Findings (일괄 code review 2026-07-13, GPT)

- [x] [Patch][High] malformed 행(비-Mapping)이 AttributeError로 재무 적재 전체를 죽임 → `_dividend_total`에 Mapping 가드(건너뜀).
- [x] [Patch][Med] `or []`가 falsy dict/str "list"를 미공시로 세탁 → None만 []로, 비-list는 dividend_ok=False(buyback 블록도 동일 수정).
- [x] [Patch][Med] 동일 라벨 상충값 첫 값 채택 → 후보 전원 일치 시만 확정, 상충·음수 혼입은 null.
- [x] [Defer][Low] 미인식 라벨 로그/집계(deferred-work).
- GPT 판정 수용: `_norm_label`이 공백 변형 흡수 확인, allowlist 정책 자체는 적절(전각 괄호 변형은 관측 시 추가).

## Dev Agent Record

### Agent Model Used

claude-fable-5 (bmad-dev-story)

### Debug Log References

- `_dividend_total`: `_norm_label`(1.8 공백 정규화 재사용) 정확일치 + `_DIVIDEND_TOTAL_LABELS` dict((라벨,스케일) 쌍만 인정 — 단위 미확인 변형은 null). 0=확정 무배당, 음수=null.
- fetch: alotMatter 호출을 buyback 블록과 동일 격리(try/except·dividend_ok·`if accounts:` 내부). normalize passthrough 제거 → rows 집계로 교체, fixture(DART_RAW_SAMSUNG)를 dividend_rows 기반으로 갱신(2,000,000백만원=2조라 기존 assertion 유지).
- run.py: dividend_ok → degraded(중복 방지 가드 포함).
- 유저 커밋(1147c85)의 `_fake_get_factory`에 alotMatter 엔드포인트 추가(기존 1.8 fetch 테스트 2건 복구).

### Completion Notes List

- pytest **163 passed**(1.9 신규 5 + 기존 158 회귀 0).
- 라이브 검증: 33종목 FY2023·FY2024 재수집 → dividend_total 커버리지 + gap_engine execution_score 소생 확인(리허설 발견 1 해소 실증) — 결과는 세션 로그 참조.

### File List

- `app/ingest/dart.py` (UPDATE: alotMatter fetch 블록·`_dividend_total`·normalize)
- `app/ingest/run.py` (UPDATE: dividend_ok degraded)
- `tests/fixtures/__init__.py` (UPDATE: dividend_rows fixture)
- `tests/test_dart_ingest.py` (UPDATE: 1.9 테스트 5종 + fake factory alotMatter)

## Change Log

- 2026-07-13: Story 1.9 생성 — 리허설 발견 1(dividend_total 구조적 100% null) 해소. 1-8 미러 설계.
- 2026-07-13: Story 1.9 구현 — alotMatter 수집(1.8 격리 미러), 163 passed. Status → review(GPT 일괄 리뷰 대기).
- 2026-07-13: 일괄 GPT 리뷰 반영(위 Review Findings) — 191 passed(리뷰 회귀 13종 추가), 재파싱·엔진 재실행 검증. Status → done.
