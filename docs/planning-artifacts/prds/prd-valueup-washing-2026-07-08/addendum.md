# PRD Addendum — 기술 상세 (HOW)

> PRD 본문(WHAT)에서 분리한 구현 상세. 정본은 아키텍처 스파인·SPEC companion에 있으며 여기선 포인터 + 요약만.

## 스택
- FastAPI 0.139.0 + Uvicorn, SQLAlchemy 2.0.51, PostgreSQL 17, alembic, APScheduler.
- 수집: dart-fss(DART), pykrx(KRX), requests(ECOS OpenAPI). 배당은 DART에서 수집(금융공공데이터 미사용).
- 정본: `.../ARCHITECTURE-SPINE.md` Stack 섹션, `specs/spec-valueup-washing/stack.md`.

## 데이터 모델 (6+2 테이블)
- 원천: `company` `financials` `prices` `valueup_plan` `ownership` `macro_indicator`
- 파생: `valuation_metrics`(SQL VIEW)
- 스코어: `valueup_score` `mna_score`
- 정본: `specs/spec-valueup-washing/db-schema.md` (실제 뷰 DDL 포함).

## SQL VIEW 지표 계산 (FR-5 구현)
- `valuation_metrics`는 물리 테이블이 아니라 **뷰**(조회 시 최신 주가 즉석 계산).
- 윈도우 함수: `LAG(...,4)`(YoY), `SUM(...) OVER (ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)`(TTM), `DISTINCT ON`(최신 시총), `NULLIF`(0 나눗셈).
- EV/EBITDA = (market_cap + total_debt − cash) / (operating_income + depreciation).

## 스코어 산식 (FR-6·7·8 구현)
- Value-up: execution_score = 100·(0.5·달성 + 0.3·자사주 + 0.2·배당). 워싱 = 진척≥0.5 & 달성<0.6 & 자사주 미이행.
- M&A: 100·(0.35·저평가 + 0.25·인수여력 + 0.25·지배구조 + 0.15·매크로), 시장 내 백분위 정규화.
- 임계치·가중치는 `config.py` 노출. 정본: `specs/spec-valueup-washing/scoring.md`.

## 아키텍처 불변식 (AD-1~10)
- AD-1 지표=SQL VIEW 전용 / AD-3 원천 writer=어댑터 / AD-4·10 스코어 writer=엔진 / AD-5 corp_code 키 / AD-6 응답 봉투 / AD-7 멱등 upsert / AD-8 as_of / AD-9 시총 단일원천.
- 정본: `.../ARCHITECTURE-SPINE.md`.

## PRD FR ↔ SPEC CAP ↔ 에픽 매핑
| PRD FR | SPEC CAP | 에픽 스토리 |
|---|---|---|
| FR-1 | CAP-1 | 1.5 |
| FR-2 | CAP-2 | 1.2, 1.3 |
| FR-3 | CAP-8 | 1.4 |
| FR-4 | CAP-9 | 1.6 |
| FR-5 | CAP-3 | 1.7 |
| FR-6 | CAP-4 | 2.1 |
| FR-7 | CAP-5 | 2.2 |
| FR-8 | CAP-10 | 2.3 |
| FR-9 | CAP-6 | 2.4, 2.5, 2.6 |
| FR-10 | CAP-7 | 3.1 |
| FR-11 | UX-DR1~4 | 3.2, 3.3, 3.4 |
| FR-12 | UX-DR5 | 3.5 |
