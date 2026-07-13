---
baseline_commit: 08a43c8
---

# Story 2.7: M&A 스코어 sector peer-group 백분위

Status: done

## Story

As a 애널리스트,
I want M&A 스코어의 저평가·인수여력 백분위가 같은 업종 peer 안에서 매겨지는 것,
so that 은행과 반도체가 같은 자로 줄 세워지는 왜곡 없이 "업종 내에서 싼 회사"를 찾는다.

## 배경

리허설 발견 2로 실증된 문제(금융주 7종 valuation+capacity null)에 대한 1단계 대응. 2.3이 파둔 grouping seam(`_build_populations(rows, group_of)`)에 sector 콜러블을 주입한다.
**정직한 스코프 경계**: 금융주는 자기 지표(ev_ebitda 등) 자체가 null이라 **이 스토리로도 부활하지 않는다** — 그건 레벨 2(업종별 변수 세트: 금융=P/B·ROE)의 몫. 이 스토리는 **비금융 업종 간 비교가능성**(반도체는 반도체끼리, 유통은 유통끼리)을 해소한다.

## Acceptance Criteria

1. **Given** `company.sector`(DART induty_code)와 2.3 grouping seam, **When** mna_engine을 실행하면, **Then** valuation·capacity의 백분위 모집단이 **KSIC 2자리 버킷**(induty_code 앞 2자리) 단위로 제한된다(택소노미 v1 = 2자리 prefix — 수작업 매핑 없이 결정적).
2. **Given** ownership_score·macro_score, **Then** 업종 무관 유지(2.7 epics AC — 지배구조 취약성과 금리는 업종 상대화 대상 아님).
3. **Given** 버킷 peer 수(해당 버킷에서 metrics 행을 가진 종목 수)가 `settings.mna_peer_min`(config, 기본 5) 미만, **Then** 그 종목의 valuation·capacity는 **전체시장 모집단으로 폴백**(small-N 노이즈 방어).
4. **Given** 어느 모집단을 썼는지 식별 요구(epics AC), **Then** `mna_score.population_basis`(신규 컬럼, 마이그레이션 0010)에 `sector:{버킷}` / `market_fallback`(버킷 미달 폴백) / `market`(sector 정보 없음)이 저장된다.
5. **Given** sector가 null/파싱불가인 종목, **Then** 전체시장 모집단 사용(`market`) — 값을 만들지 않고 정직하게 분류.
6. **Given** 재실행, **Then** 멱등 + 기존 2.3 계약(엄격 null·look-ahead·reconciliation·전체실행 권장) 전부 보존, 기존 163 테스트 회귀 0.

## Tasks / Subtasks

- [x] **T1**: config에 `mna_peer_min: int = Field(5, ge=2)` 추가(NFR3).
- [x] **T2**: `MnaScore.population_basis`(String(20), nullable) + 마이그레이션 0010(revises 0009).
- [x] **T3**: repo `all_company_sectors(session) -> dict[corp_code, sector]` 추가(AD-2).
- [x] **T4**: engine — `_sector_bucket(sector) -> str | None`(2자리 prefix, 숫자 아니면 None), run()에서 버킷별 population 구성(`_build_populations` seam에 주입) + 종목별 basis 결정(sector/fallback/market) + valuation·capacity만 버킷 모집단 사용.
- [x] **T5**: 테스트 — 버킷 분리로 순위가 바뀌는 시나리오(같은 값이라도 업종 내 상대화), peer<min 폴백, sector null → market, basis 저장, 회귀 0.

## Dev Notes

- **2.3 seam 그대로**: `_build_populations`는 이미 group_of 콜러블을 받는다 — 엔진 재작성 없음. 버킷 모집단과 시장 모집단을 **둘 다** 만들어 폴백 시 참조.
- **폴백 단위 = 버킷**(metric별 아님): 버킷의 metrics 종목 수 < min이면 그 버킷 전체가 폴백 — basis 문자열이 단일 의미를 갖도록(metric별 혼합 방지).
- **ownership은 시장 모집단 유지**: "최대주주 지분율이 낮다"는 업종 불문 절대적 취약성 신호(epics AC 명시).
- 레벨 2(변수 세트 교체)는 이 스토리 known-limitation — 금융주 null은 그대로임을 리포트에 명시.

### Review Findings (일괄 code review 2026-07-13, GPT)

- [x] [Patch][High] sector 승격이 '행 개수' 기준이라 지표별 small-N 방어 우회(행 6개·ev_ebitda 유효 2개면 N=2 백분위) → **지표별 유효값 개수** 기준으로 변경: 5개 서브지표 전부 peer_min 이상일 때만 sector, 아니면 버킷 전체 시장 폴백(단일 basis 의미 보존).
- [x] [Patch][Med] metrics 없는 종목에도 sector basis 기록(과장) → valuation·capacity 둘 다 null이면 basis=None.
- [x] [Defer][Med] 원천별 watermark 검증(deferred-work, score_run 계열).

## Dev Agent Record

### Agent Model Used

claude-fable-5 (bmad-dev-story)

### Debug Log References

- `_sector_bucket`: KSIC 2자리 prefix(비숫자/누락 → None→market). seam(`_build_populations`)에 sector group_of 주입 — 엔진 구조 변경 없음(2.3 설계 의도 실증).
- 폴백 단위=버킷(metric별 아님): basis 문자열 단일 의미 보장. ownership·macro는 시장/역사 모집단 유지(epics AC).
- 시장·버킷 모집단을 둘 다 구성해 폴백 시 참조. upsert 필드에 population_basis 추가.

### Completion Notes List

- pytest **166 passed**(2.7 신규 3 + 기존 163 회귀 0). 마이그레이션 0010.
- 라이브 검증(33종목): basis 분포 = sector:64(금융지주 5종목, min 충족) + market_fallback 26 — 소형 유니버스에서 폴백이 설계대로 동작, 전체시장에선 버킷 자연 활성화. 금융주 valuation null은 레벨 2(변수 세트) 한계 그대로(스토리 스코프 명시대로).

### File List

- `app/config.py` (UPDATE: mna_peer_min)
- `app/models.py` (UPDATE: MnaScore.population_basis)
- `alembic/versions/0010_mna_population_basis.py` (NEW)
- `app/repositories/mna_score.py` (UPDATE: all_company_sectors + upsert 필드)
- `app/analysis/mna_engine.py` (UPDATE: _sector_bucket + 버킷 모집단/폴백/basis)
- `tests/test_mna_engine.py` (UPDATE: 2.7 테스트 3종)

## Change Log

- 2026-07-13: Story 2.7 생성·착수 — 리허설 발견 2 대응 1단계(KSIC 2자리 버킷 + 폴백 + basis 식별).
- 2026-07-13: Story 2.7 구현 — KSIC 2자리 버킷+폴백+basis, 166 passed, 라이브 검증(sector:64 활성). Status → review(GPT 일괄 리뷰 대기).
- 2026-07-13: 일괄 GPT 리뷰 반영(위 Review Findings) — 191 passed(리뷰 회귀 13종 추가), 재파싱·엔진 재실행 검증. Status → done.
