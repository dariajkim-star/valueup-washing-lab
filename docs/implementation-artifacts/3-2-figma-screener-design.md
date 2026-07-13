---
baseline_commit: 00bfd1c
---

# Story 3.2: Figma 애널리스트 스크리너 UI 디자인

Status: done

## Story

As a 디자이너/개발자,
I want Figma MCP로 실제 금융 플랫폼 같은 스크리너를 디자인하는 것,
so that 클릭 흐름을 가진 프로토타입 기준 시안이 생긴다.

## Acceptance Criteria

1. **Given** Figma MCP 연동과 UX-DR1~4, **When** 스크리너 화면을 생성하면, **Then** 4개 핵심 프레임(필터 패널·종목 리스트·종목 상세·투자 포인트 카드)이 만들어진다.
2. **Given** 스코어 모드(Value-up ↔ M&A) 전환 요구(UX-DR1), **Then** 두 모드의 리스트/상세 상태가 시안에 존재한다(모드에 따라 강조 컬럼·상세 분해가 바뀜).
3. **Given** API 필드 매핑(FR6/Epic 2), **Then** 각 데이터 요소가 실제 API 필드(`execution_score`·`mna_target_score`·`washing_flag`·`buyback_status`·`population_basis`·`has_valueup_score`/`has_mna_score` 등)와 1:1로 매핑되고, 시안 주석/네이밍에 그 매핑이 드러난다.
4. **Given** Epic 2 회고 액션아이템(null 시각 언어 확정), **Then** 아래 "null/불확실 상태 시각 언어"가 시안에 실제 컴포넌트로 구현된다 — 판단 불가·산출 불가·엔진 미집계·업종 미지원·모집단 근거(population_basis)가 각각 구분되는 시각 표현을 갖는다(빈칸·0·"아니오"로 뭉개지 않음).
5. **Given** 클릭 흐름 프로토타입, **Then** 리스트에서 종목 선택 → 상세로 이동하는 인터랙션이 연결된다.
6. **Given** 산출물 인계, **Then** 3.3(필터·리스트)·3.4(상세·카드) 구현이 참조할 수 있도록 시안 위치(Figma 파일 URL 또는 프레임)·데이터 매핑·컴포넌트 스펙이 이 문서에 기록된다.

## 🎨 null/불확실 상태 시각 언어 (Epic 2 회고 액션아이템 확정)

Epic 2의 API 3종(2.4/2.5/2.6)이 지켜온 null 계약을 화면 언어로 확정한다. **원칙: 정직성 우선 — API가 어렵게 지킨 "모름"을 화면에서 빈칸/기본값/0으로 뭉개지 않는다.** 5가지 상태를 시각적으로 구분한다:

| 상태 | 의미 | API 근거 | 시각 표현 |
|---|---|---|---|
| **워싱 의심** | washing_flag=true | 2.4 | 앰버/레드 배지 "⚠ 워싱 의심" |
| **근거 없음** | washing_flag=false | 2.4 | 중립 회색 텍스트 "해당 없음"(강조 안 함) |
| **판단 불가** | washing_flag=null | 2.4 계약 | 점선 회색 pill "판단 불가" + ⓘ 툴팁("데이터 부족으로 워싱 판정 불가"). **빈칸/"아니오" 금지** |
| **산출 불가** | mna_target_score=null (엄격 게이팅) | 2.5 계약 | "—" + 회색 캡션 "산출 불가" + ⓘ 툴팁("요소 지표 결측"). **0점/최하위 금지** |
| **엔진 미집계** | has_valueup_score=false 또는 has_mna_score=false | 2.6 계약 | 더 옅은 대시 플레이스홀더 "· · ·" + 툴팁("아직 집계되지 않음"). 산출 불가와 **구분**(엔진이 안 돈 것 vs 돌았지만 계산 불가) |

추가 2요소:
- **모집단 근거(population_basis)**: M&A 스코어 아래 작은 chip — `업종 내 (KSIC 26)`(sector) / `전체시장 폴백`(market_fallback) / `전체시장`(market). 백분위 해석에 필수(2.7).
- **미지원 업종**: 금융주 등 valuation/capacity가 구조적으로 null인 섹터는 M&A 스코어 자리에 카드/행 레벨 안내 "이 업종은 M&A 스코어 미지원(은행·보험 등)" — 드레스 리허설 발견 2 대응. 개별 "산출 불가"의 반복이 아니라 업종 단위 설명.

이 시각 언어는 3.3(리스트 배지·정렬)·3.4(상세 분해)가 그대로 구현 참조로 쓴다.

## Tasks / Subtasks

- [x] **T1**: Figma 연동 확인(whoami=daria.j.kim@gmail.com) + 새 디자인 파일 생성("Jeongeun Kim의 팀" Full seat).
- [x] **T2**: 팔레트(중립 그레이 + Value-up 그린 #0E9F6E / M&A 인디고 #4F46E5 / 워싱 앰버 #B42318 / null 그레이 #9CA3AF 점선), null 상태 5종 시각 표현.
- [x] **T3**: 필터 패널(UX-DR1) — 시장·업종·시총·ROE/PBR/EV·EBITDA/부채비율 슬라이더, 워싱 토글, Value-up↔M&A 세그먼트 전환.
- [x] **T4**: 종목 리스트(UX-DR2) — 6행(드레스 리허설 실종목)으로 정상·판단불가·미집계·산출불가·미지원업종·워싱의심 6상태 전부 + population_basis chip.
- [x] **T5**: 종목 상세(UX-DR3) — ROE 분기 시계열 바차트, "계획 vs 실제" 갭 카드(목표 12%→실제 15.1%→갭 +3.1%p, 달성률/진척률/자사주), M&A 4요소 분해.
- [x] **T6**: 투자 포인트 카드(UX-DR4) — 밸류업(고ROE·자사주 실이행)/M&A(저평가·저부채) 자동 태깅.
- [x] **T7**: 클릭 흐름 프로토타입(기아 행→상세, SMART_ANIMATE) 연결 + 리스트 시작점.
- [x] **T8**: 아래 인계 기록.

## Dev Notes

### 접근 방식

- Figma MCP `use_figma`/`generate_figma_design`를 쓰기 전 **반드시 figma-use·figma-generate-design 스킬을 로드**(MCP 필수 프리레퀴짓). 이 스토리는 코드 산출물이 아니라 **디자인 시안**이므로 pytest 회귀 대상 없음(기존 221 테스트 불변).
- 데이터는 목업 값을 쓰되 **실제 API 응답 형태**(2.4~2.6·3.1 스키마)를 반영 — 3.3/3.4가 시안을 그대로 코드로 옮길 때 필드명이 어긋나지 않게. 예: 리스트 행 = `/screening` 응답의 ScreeningOut, 상세 = valueup_score+mna_score+valuation_metrics.
- 실데이터 감각을 위해 드레스 리허설 실제 종목(포스코홀딩스 M&A 71.1, 금융주 산출 불가, 워싱 0건)을 목업 샘플로 사용 — "정직한 null"이 실제로 어떻게 보이는지 시안에 담김.

### 아키텍처 정합

- AD-11(프론트는 REST API로만, 서버상태 TanStack Query/UI상태 분리) — 이 시안은 3.3/3.4가 AD-11대로 구현할 화면의 기준. 시안의 모든 데이터 요소는 Epic 2/3.1 API로 조달 가능해야 함(DB 직접 접근 전제 금지).
- 스코어 모드 전환은 UI 상태(로컬), 리스트 데이터는 서버 상태 — 시안에서 두 관심사가 섞이지 않게 표현.

### 스코프 경계

- 이 스토리는 **시안(디자인)만**. React 구현은 3.3(필터·리스트)·3.4(상세·카드). Tableau는 3.5.
- 실제 API 연결·상태관리 코드 없음 — 목업 데이터 기반 정적/프로토타입 시안.

## 인계 기록 (T8 — 3.3/3.4 구현 참조)

### Figma 시안

- **파일 URL**: https://www.figma.com/design/y3WqLBWZNaPbOCaiP60jUe (파일키 `y3WqLBWZNaPbOCaiP60jUe`, 페이지 "애널리스트 스크리너 v1")
- **소유**: daria.j.kim@gmail.com / "Jeongeun Kim의 팀" 플랜
- **프레임**: Screen 1 스크리너(node 1:2) · Screen 2 종목 상세(node 7:2) · 범례 시트 null 시각 언어(node 11:2)
- **프로토타입**: Screen 1이 시작점, 기아 행(node 5:20) 클릭 → Screen 2(SMART_ANIMATE 0.3s)

### 데이터 → API 필드 매핑 (3.3/3.4가 그대로 구현)

| 화면 요소 | API 소스 | 필드 |
|---|---|---|
| 리스트 행 | `GET /screening` (ScreeningOut) | corp_name·market·execution_score·mna_target_score·washing_flag·population_basis·has_valueup_score·has_mna_score |
| Value-up 컬럼 | 위 | execution_score (null→"미집계" if has_valueup_score=false) |
| M&A 컬럼 + chip | 위 | mna_target_score + population_basis(sector→"업종 내", market_fallback→"전체시장 폴백") |
| 워싱 배지 | 위 | washing_flag (true→워싱 의심 / false→근거 없음 / null→판단 불가) |
| 상세 헤더 스코어 | `/screening` 또는 개별 조회 | execution_score·mna_target_score |
| 지표 시계열 | `GET /metrics/{corp_code}` | roe·pbr 분기 시리즈 |
| 계획 vs 실제 갭 | `/valueup/gap-analysis` (GapAnalysisOut) | target_roe·actual_roe·roe_gap·achievement_rate·progress_rate·buyback_status |
| M&A 4요소 분해 | `/mna/ranking` (MnaRankingOut) | valuation_score·capacity_score·ownership_score·macro_score·population_basis |
| 투자 포인트 태깅 | 위 지표·스코어 조합(프론트 규칙) | 고ROE·저PBR·자사주 실이행 / 저평가·저부채·낮은 지분율 |
| 필터 패널 | `/screening` 쿼리 파라미터 | market·sector·min/max_execution_score·min/max_mna_score·washing_only·sort |
| 스코어 모드 전환 | UI 상태(로컬, AD-11) | sort 필드·강조 컬럼 전환(서버 재요청) |

### 컴포넌트 스펙 (null 시각 언어 — 위 🎨 섹션이 원본, 범례 시트 node 11:2에 실물)

- 판단 불가·미집계 = 점선 회색 pill / 산출 불가 = "—" + 회색 캡션 / 미지원 업종 = 회색 pill + 업종 예시 / 워싱 의심 = 앰버 pill + 행 배경 살짝 틴트.
- **금칙**: null을 빈칸·0·"아니오"로 표기 금지(2.4~2.6 API 계약 승계).

## Dev Agent Record

### Agent Model Used

claude-fable-5 (bmad-create-story + figma-use/figma-create-new-file 스킬)

### Completion Notes List

- Figma 시안 완성 — 스크리너·상세·범례 3프레임 + 클릭 프로토타입. 코드 산출물 없음(디자인 스토리) → **pytest 회귀 대상 없음, 기존 221 테스트 불변**.
- null 시각 언어 6상태(회고 액션아이템)를 리스트에 실물로 구현하고 범례 시트로 문서화 — 3.3/3.4의 구현 기준 확정.
- 목업 데이터는 드레스 리허설 실종목(포스코홀딩스·기아·네이버·크래프톤·신한금융지주) 사용 — "정직한 null"이 실제로 어떻게 보이는지 시안에 반영.
- 리드 확인 대기 사항: 시안의 시각 언어(색·문구)는 제안 기본값 — 변경 요청 시 3.3 착수 전 조정 가능.

### File List

- Figma 파일 `y3WqLBWZNaPbOCaiP60jUe`(코드 저장소 외부 산출물)
- `docs/implementation-artifacts/3-2-figma-screener-design.md` (이 문서)

## Change Log

- 2026-07-13: Story 3.2 생성 — Figma 스크리너 시안. Epic 2 회고 액션아이템(null 시각 언어)을 6상태 시각 언어로 확정(워싱의심·근거없음·판단불가·산출불가·미집계·미지원업종 + population_basis), Epic 2/3.1 API 스키마를 데이터 매핑 기준으로 고정.
- 2026-07-13: Story 3.2 구현 — Figma 파일 생성, 스크리너/상세/범례 3프레임 + 클릭 프로토타입 완성, API 필드 매핑·컴포넌트 스펙 인계 기록. Status → done.
