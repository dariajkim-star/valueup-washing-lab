---
baseline_commit: 08a43c8
---

# Story 1.10: 밸류업 공시 파서 튜닝 (실샘플 기반)

Status: done

## Story

As a 애널리스트,
I want 밸류업 계획공시의 목표치 파싱률이 실샘플 기준으로 개선되는 것,
so that 갭 스코어(achievement_rate) 커버리지가 실사용 가능한 수준이 된다.

## Acceptance Criteria (epics.md 1.10)

1. report_nm 부정 필터(이행현황·철회 제외, 정정 유지)로 계획 아닌 공시 배제.
2. 실샘플 기반 정규식 개선 + 재파싱, before/after 측정.
3. raw_text 보존·전체교체 upsert로 파괴 없는 재파싱(1.5 원칙).

## Tasks / Subtasks

- [x] **T1**: `_is_plan_report`(F9) — 이행현황·철회 제외, 정정 유지. fetch 적용.
- [x] **T2**: 실샘플 실증 패턴 4종 — (a) 괄호 한정어 gap(`ROE 목표(\`24~\`30년 평균) : 15%`), (b) 자기자본이익률 별칭, (c) 화살표 체인 우변 채택(`1.8% → 8.3%`, F3/G2), (d) 백틱 2자리 연도 기간(`\`24~\`30년`, 표식 필수로 '24~26개월' 오탐 방지).
- [x] **T3**: 라이브 재수집(F9는 fetch 레벨) + before/after 측정.
- [x] **T4**: 테스트 8종(실샘플 케이스 그대로) + 기존 회귀 0.

### Review Findings (일괄 code review 2026-07-13, GPT — "정규식이 남의 숫자를 훔침")

- [x] [Patch][High] 괄호 한정어가 %·경쟁 지표 허용 → `ROE(2024년 5%) 배당성향 30%`가 30을 ROE로. tempered gap(경쟁 라벨·괄호 내 % 금지)으로 재작성 — 실샘플 recall 손실 0 확인(재파싱 25/8 유지).
- [x] [Patch][High] 화살표가 다른 지표의 체인을 훔침 → 좌·중 gap에 경쟁 라벨 금지.
- [x] [Patch][High] `_get_json` 비-dict JSON이 AttributeError로 누출(페이지 격리 계약 파괴) → ValueError 포착+dict 검증+item Mapping 가드.
- [x] [Patch][Med] 화살표가 앞선 명시 목표를 무조건 이김 → 위치 우선(앞선 매칭 승).
- [x] [Patch][Med] 기간이 문서 첫 범위 고정(과거 비교기간 오인) → `_select_period`(계획·목표·향후·중장기 앵커 우선, 앵커 없이 상이 다수면 null). '기간' 키워드는 "비교기간" 역효과로 제외.
- [x] [Patch][Med] zip 누적 상한 부재 → 총 50MB·멤버 200개 상한.
- 재파싱 검증: 60건 기준 roe 25·payout 8 유지(오탐 차단이 recall을 깎지 않음), period 17→16(앵커 없는 애매 범위 1건이 정직하게 null — 의도된 강화).

## Dev Agent Record

### Agent Model Used

claude-fable-5 (bmad-dev-story)

### Debug Log References

- 개선은 전부 **실샘플 79건에서 실증된 패턴만**(관념적 개선 금지): 분석 스크립트로 미파싱 문맥을 뽑아 원인별 대응. 괄호 밖 gap은 여전히 숫자 금지(1.5 F2 인접 지표 방어 유지), 2자리 연도는 백틱/따옴표+년 표식 필수.
- 화살표 규칙: 화살표 체인 존재 시에만 우변, 없으면 기존 첫 매칭(회귀 방지 테스트 포함).

### Completion Notes List

- **before/after(33종목 라이브)**: 문서 79→60건(이행현황·철회 19건 배제 — 가짜 계획 정리), target_roe 24%→**42%**, period 13%→**28%**, payout 14%→13%(제거된 이행현황 문서의 오탐 파싱이 빠진 효과 포함). 다운스트림: achievement_rate 2→6종목, progress 4→11, **execution_score 0→1(최초 non-null)**.
- **남은 병목 = target_payout**: 주주환원율-only 공시 25건은 의도적 미매핑(1.5/2.1 의미 결정 — 배당성향≠주주환원율). 커버리지를 더 올리려면 `target_shareholder_return_ratio` 별도 필드 스토리 필요(스코프 밖, deferred).
- pytest **173 passed** 시점 검증(이후 2.4 포함 178).

### File List

- `app/ingest/dart_valueup.py` (UPDATE: `_is_plan_report`·`_LABEL_GAP`·별칭·화살표·2자리 연도)
- `tests/test_valueup_ingest.py` (UPDATE: 실샘플 테스트 8종)

## Change Log

- 2026-07-13: Story 1.10 구현 — F9+실증 패턴 4종, 재수집·재파싱, target_roe 24→42%. Status → review(GPT 일괄 리뷰 대기).
- 2026-07-13: 일괄 GPT 리뷰 반영(위 Review Findings) — 191 passed(리뷰 회귀 13종 추가), 재파싱·엔진 재실행 검증. Status → done.
