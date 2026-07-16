# 밸류업 워싱 스크리너 (Value-up Washing Screener)

상장사의 **밸류업 계획 공시**(목표 ROE·배당성향·자사주)와 **실제 실적**을 금융감독원 OpenDART·KRX·한국은행 ECOS 실데이터로 대조해, "말만 하고 지키지 않는" 기업을 정량 스코어링·랭킹하는 스크리너입니다. 밸류업 이행 점수와 별도로 **M&A 타겟 스코어**(저평가·인수여력·지배구조·매크로)를 함께 제공합니다.

> 정책 맥락(2026): 밸류업 공시 사실상 의무화(718개사), 상법 개정 자사주 의무소각, 코스피 PBR 1.3배 vs 글로벌 2.3배 — "공시 대비 이행 갭"이 실제 투자·심사 판단의 재료가 되는 시점.

## 무엇을 볼 수 있나 (화면부터)

**① 애널리스트 스크리너 (React SPA)** — 시장·업종·시총·지표(ROE/PBR/EV/EBITDA/부채비율) 필터와 워싱 토글로 종목을 좁히고, Value-up ↔ M&A 스코어 모드를 전환하며 탐색합니다.

**② 종목 상세 & 투자 포인트 카드** — 지표 시계열, "계획 vs 실제" 갭 카드, M&A 4요소 분해, 자동 태깅(고ROE·저PBR·자사주 실이행 / 저평가·저부채·낮은 지분율). 근거 지표가 null이면 태그를 만들지 않습니다.

**③ Tableau 대시보드** — 밸류업 점수·업종 저평가 맵·ROE-PBR 산점도·배당/자사주 4개 뷰 + ECOS 매크로 레이어. CSV 스냅숏(원자적 교체 + manifest)을 소스로 사용합니다.

**④ 그 아래** — FastAPI 5개 라우터(`/screening`·`/valueup`·`/mna`·`/metrics`·`/stats`), 2개 스코어링 엔진(gap_engine·mna_engine), SQL VIEW 기반 파생지표, 3개 소스 수집 어댑터.

## 설계 원칙 하나만 꼽는다면: 정직한 null

이 프로젝트의 관통 원칙은 **"판단할 수 없는 것을 판단한 척하지 않는다"**입니다.

- 워싱 판정은 Kleene 3치 논리 — 소각을 확정한 기업은 진척률을 몰라도 확정 False, 근거가 부족하면 True/False가 아니라 **null("판단 불가")**. 실데이터 33종목에서 False 18 / 판단 불가 8 / True 0으로 설계대로 작동함을 검증했습니다.
- 이 null이 **DB → API → React 화면 → CSV → Tableau까지 다섯 레이어를 관통**합니다. API는 `has_valueup_score`/`has_mna_score`로 "엔진 미실행"과 "판정 불가"를 구분하고, 화면은 6가지 상태(판단불가·산출불가·미집계·미지원업종 등)를 각각 다른 시각 언어로 그리며, CSV는 null을 빈 셀로 보존하고(0 치환 금지), Tableau 트리맵은 미산정 종목 수를 명시 노출합니다.
- 신용평가·심사 도메인에서 "불확실을 확실로 세탁하지 않는 것"은 스타일이 아니라 요구사항이라고 판단했습니다.

## 실행 방법

요구사항: Python 3.11+(.venv), Node 20+, `.env`에 `DART_API_KEY`·`ECOS_API_KEY`·`KRX_ID`/`KRX_PW`(수집 시에만 필요 — 테스트는 키 없이 전부 통과).

```bash
# 0) 설치
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
cd dashboard && npm install && cd ..

# 1) 백엔드 API  →  http://localhost:8000/docs
.venv/Scripts/uvicorn app.main:app --reload

# 2) 프론트 대시보드  →  http://localhost:5175 (Vite proxy → :8000)
cd dashboard && npm run dev

# 3) Tableau용 CSV 스냅숏  →  exports/tableau/*.csv + manifest.json
.venv/Scripts/python -m app.export.tableau            # 두 엔진 공통 최신 기준일
.venv/Scripts/python -m app.export.tableau --as-of 2026-07-13   # 과거 시점 재현
```

데이터 수집·스코어링은 Python API로 실행합니다(단일 사용자 로컬 도구라 별도 CLI 대신 함수 직접 호출):

```python
from app.db import SessionLocal
from app.ingest import run as ingest          # ingest_financials / prices / macro / valueup_plans / ownership
from app.analysis import gap_engine, mna_engine

s = SessionLocal()
gap_engine.run(s, as_of="2026-07-13")         # valueup_score 계산·upsert (유일 writer)
mna_engine.run(s, as_of="2026-07-13")         # mna_score 계산·upsert (유일 writer)
```

테스트: `pytest -q`(백엔드 246) · `cd dashboard && npm test`(프론트 56) · 마이그레이션 `alembic upgrade head`(0001~0011).

## 아키텍처 (AD 요약)

Layered 서빙 + Pipes-and-Filters 수집. 전체 규칙은 [ARCHITECTURE-SPINE](docs/planning-artifacts/architecture/architecture-valueup-washing-2026-07-08/ARCHITECTURE-SPINE.md), API 계약은 [API_SPEC](docs/API_SPEC.md).

| 결정 | 규칙 |
|---|---|
| AD-1 | 파생지표(ROE·PBR·EV/EBITDA…)는 **DB SQL VIEW**(`valuation_metrics`)로만 — 앱코드 재계산 금지 |
| AD-2 | SQL은 repository 레이어에서만, 의존은 단방향(routers→services→repositories) |
| AD-3/4/10 | 원천 테이블 writer는 수집 어댑터뿐, `valueup_score`/`mna_score` writer는 각 엔진뿐 |
| AD-5 | `corp_code`(DART 8자리)가 정식 엔티티 키 |
| AD-6 | 응답 봉투(`items/total/page/size`)·에러 계약(`{detail, code}`) 전 라우터 공통 |
| AD-7 | 수집 적재는 멱등 upsert |
| AD-8 | 스코어에 `as_of` 신선도 스탬프 — 시스템 시계 대신 명시 기준일 |
| AD-11 | 프론트는 REST API로만 데이터 접근(DB 직접 접근 금지), 서버상태 TanStack Query·UI상태 zustand 분리 |

스택: FastAPI + SQLAlchemy 2.0(SQLite 개발/PostgreSQL 지원) · React 19 + Vite + TanStack Query/Table + Recharts · Tableau(CSV 스냅숏) · 수집은 OpenDART **REST 직접 호출**(dart-fss는 XBRL 파싱 불안정으로 제거 — 실전 트러블슈팅 판단) + pykrx + ECOS REST.

## 개발 방식: AI 교차검증 워크플로우

BMAD 스토리 단위(3에픽 22스토리)로 개발하고, 매 스토리를 **구현 모델(Claude)과 다른 모델(GPT)이 교차 리뷰**했습니다. 리뷰 번들에 코드 전문을 verbatim으로 넣는 것이 규칙이며(축약 금지), 발견 사항은 patch/defer/dismiss로 triage해 스토리 문서에 전량 기록했습니다.

- 누적으로 매 스토리 실질 결함이 발견됨 — 예: pydantic ValidationError가 ValueError 하위라 내부 오류가 400으로 세탁되는 함정(2.6), 4개 API 병렬 호출의 기준일 혼합(3.4), 스냅숏 부분 실패 시 세대 혼합(3.5).
- 리뷰가 반려한 스토리(3.3)는 재작업 후 3라운드까지 갔고, 라운드가 거듭될수록 지적이 구조적→세부로 수렴하는 패턴을 확인했습니다.
- 리뷰어 처방을 그대로 따르지 않고 더 싼 해법을 택해 관철한 사례(3.4 as_of 체이닝, 3.5 교집합 기준일)와, 리뷰어 오탐을 사실관계로 반박·기각한 사례도 스토리 문서에 남아 있습니다.

에픽별 회고: [Epic 1](docs/implementation-artifacts/epic-1-retro-2026-07-10.md) · [Epic 2](docs/implementation-artifacts/epic-2-retro-2026-07-13.md) · [Epic 3](docs/implementation-artifacts/epic-3-retro-2026-07-14.md)

## 한계와 판단 (의도적으로 안 한 것들)

포트폴리오 프로젝트로서, 리스크를 식별하고도 **비용 대비 판단으로 미구현을 선택한 항목**을 명시합니다. 상세는 [deferred-work](docs/implementation-artifacts/deferred-work.md).

1. **execution_score 커버리지가 낮다(실데이터 33종목 중 non-null 1종목)** — 원인은 코드가 아니라 원천 데이터: 밸류업 공시의 목표치가 자유서식(범위·서술형)이라 target 파싱이 구조적으로 어렵습니다. 파서 튜닝으로 24%→42%까지 개선한 실적이 있고, 남은 갭은 수확체감 구간으로 판단해 **낮은 커버리지를 숨기지 않고 정직하게 노출하는 쪽을 설계 원칙으로 채택**했습니다. 워싱 판정의 핵심 신호(washing_flag)는 19종목에서 정상 작동합니다.
2. **score_run 배치 메타데이터 미구현** — 엔진 부분 실행이 `latest_as_of`를 오염시킬 수 있는 리스크를 인지했으나, 단일 사용자 로컬 도구라는 운용 조건과 이미 구축된 완화 장치(Tableau 교집합 기준일+manifest, API의 `has_*_score` 플래그)를 고려해 기록으로 마감했습니다. 운영 서비스화 시에는 실행 단위 메타데이터 테이블이 정답입니다.
3. **가격 point-in-time 미보장** — `valuation_metrics` 뷰가 과거 `as_of` 조회에도 전역 최신가를 사용합니다. 과거 시점 백테스트 용도로는 부적합하며, 해소하려면 가격 이력 조인 재설계가 필요합니다.
4. **look-ahead "부분 차단"** — 같은 해 사업보고서(확정적으로 미래 공시)만 배제하고, 1~3분기 보고서의 동일 연도 시차는 실제 공시일(`available_at`) 데이터 없이는 차단할 수 없습니다. 전 엔드포인트가 동일 규칙을 공유해 API-CSV 패리티는 유지됩니다.
5. **배포 envelope 없음** — 의도적 로컬 전용(아키텍처 결정). 운영 배포 시 SPA rewrite 설정·DB 전환(PostgreSQL 드라이버 동봉)이 필요합니다.

이 판단들은 사후 CX 분석으로 교차 검증했습니다: 고객 여정 지도·Google HEART·IPA 세 방법론이 독립적으로 **§1(커버리지)을 유일한 "집중 개선" 구역**으로, 품질 투자 지점(오탐 방지·정직한 null·배선 실증)을 "강점 유지" 구역으로 수렴시킵니다 — [cx-analysis](docs/cx-analysis-2026-07-16.md), v2 우선순위는 [v2-backlog](docs/implementation-artifacts/v2-backlog.md).

## 저장소 안내

```
app/            FastAPI·엔진·수집·export (ingest / analysis / repositories / services / routers / export)
dashboard/      React SPA (스크리너 + 종목 상세)
docs/           API_SPEC + 계획 아티팩트(PRD·아키텍처·에픽) + 구현 아티팩트(스토리 22건·리뷰 번들·회고 3건)
exports/        Tableau CSV 스냅숏 + 워크북 (재생성 가능, gitignore)
tests/          pytest 246 (합성 데이터 — API 키 없이 전부 통과)
```
