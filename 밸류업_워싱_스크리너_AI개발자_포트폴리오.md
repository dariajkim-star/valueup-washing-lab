# 1. 프로젝트 명

**밸류업 워싱 스크리너 (Value-up Washing Screener)**

------------------------------------------------------------------------

# 2. 프로젝트 개요

**AX 자동화 실습**

상장사의 **밸류업 계획 공시(DART)**와 **분기 재무제표, KRX 주가
데이터**를 통합하여 공시 내용과 실제 이행 여부를 비교·분석하는 금융
데이터 분석 시스템.

DART OpenAPI, pykrx, 금융공공데이터를 활용한 **데이터 파이프라인 구축**,
SQL 기반 재무지표 계산과 **밸류업 갭 분석 엔진(Analysis Engine)**을 통해
계획 대비 실제 이행 수준을 **달성률(Achievement), 진척률(Progress), 워싱
플래그(Washing Flag), 밸류업 실행 점수(Execution Score)**로 정량화.

FastAPI 기반 **REST API 구축**, Tableau 및 Figma와 연계 가능한
애널리스트 스크리닝 데이터 제공.

------------------------------------------------------------------------

# 3. 사용 기술 및 도구

  ---------------------------------------------------------------------------------
  **카테고리**                        **보유 기술 / 활용 경험**
  ----------------------------------- ---------------------------------------------
  **프로그래밍 언어**                 Python

  **데이터 처리 및 분석**             Pandas, NumPy, SQL(DDL/DML), SQL VIEW, CTE,
                                      Window Function(LAG), 다중 JOIN, 재무지표
                                      계산(ROE·ROA·PBR·PER·부채비율·배당성향·YoY)

  **머신러닝**                        정량 스코어링(Scoring), Rule-based Analysis
                                      Engine

  **자연어 처리 / 생성형 AI**         DART 밸류업 공시 파싱, 정규식 기반 목표
                                      ROE·배당성향·목표 PBR·자사주 계획 추출

  **웹서비스 구축**                   FastAPI, REST API, OpenAPI, SQLAlchemy 2.0,
                                      PostgreSQL, SQLite, Uvicorn, Pydantic v2

  **협업 / 개발환경**                 Git, GitHub, Alembic, pytest, httpx

  **AI 활용·자동화**                  APScheduler, DART OpenAPI, pykrx,
                                      금융공공데이터 API, 데이터 파이프라인 자동화,
                                      Tableau, Figma
  ---------------------------------------------------------------------------------

------------------------------------------------------------------------

# 4. 수행 역할 & 5. 수행 내용

### 데이터 파이프라인 구축

-   DART OpenAPI, pykrx, 금융공공데이터 API 연동
-   APScheduler 기반 일배치 데이터 수집 자동화
-   기업 정보, 재무제표, 주가 데이터 통합 파이프라인 구축
-   corp_code와 stock_code 매핑 구조 설계
-   데이터 수집 예외 처리 및 캐시 구조 적용

### 데이터베이스 설계

-   PostgreSQL 기반 데이터베이스 설계
-   company, financials, prices, valueup_plan, valuation_metrics,
    valueup_score 테이블 설계
-   SQLAlchemy ORM 적용
-   Alembic 기반 데이터베이스 마이그레이션 관리

### SQL 기반 재무지표 분석

-   SQL VIEW 기반 valuation_metrics 설계
-   CTE, Window Function(LAG), 다중 JOIN 활용
-   ROE, ROA, PBR, PER, 부채비율, 배당성향, YoY 성장률 계산
-   조회 시점 최신 데이터를 반영하는 재무지표 분석 구조 설계

### 밸류업 갭 분석 엔진 (Analysis Engine)

-   DART 밸류업 공시 파싱
-   목표 ROE, 목표 배당성향, 목표 PBR, 자사주 계획 추출
-   계획 대비 실제 실적 비교 분석
-   달성률(Achievement), 진척률(Progress) 계산
-   워싱 플래그(Washing Flag) 판별 로직 설계
-   밸류업 실행 점수(Execution Score) 산출

### REST API 구축

-   FastAPI 기반 REST API 구축
-   기업 상세 조회 API
-   밸류업 실행 점수 랭킹 API
-   워싱 기업 스크리닝 API
-   시장 및 업종 통계 API
-   필터, 정렬, 페이지네이션 구현
-   OpenAPI 문서 자동화

### 데이터 시각화

-   Tableau 대시보드 설계
-   밸류업 실행 점수 랭킹 시각화
-   업종별 저평가(PBR) 히트맵
-   ROE-PBR 산점도
-   배당 및 자사주 실이행 현황 시각화
-   Figma 기반 애널리스트 스크리너 UI 설계

------------------------------------------------------------------------

# 6. 성과 및 결과

-   DART, KRX, 금융공공데이터를 통합한 금융 데이터 파이프라인 구축
-   SQL VIEW, CTE, Window Function(LAG)을 활용한 재무지표 계산 자동화
-   밸류업 갭 분석 엔진(Analysis Engine) 설계
-   달성률(Achievement), 진척률(Progress), 워싱 플래그(Washing Flag),
    밸류업 실행 점수(Execution Score) 기반 정량 평가 체계 구축
-   FastAPI 기반 REST API 구축 및 Tableau·Figma 연계 데이터 제공 구조
    구현
-   데이터 수집 → DB 구축 → 재무지표 분석 → 밸류업 갭 분석 → REST API →
    시각화로 이어지는 **End-to-End 금융 데이터 분석 시스템 구축**
-   공시의 '계획'과 실제 재무성과 및 주주환원 활동을 비교하여 밸류업
    워싱 기업을 정량적으로 탐지하는 금융 스크리닝 모델 구현
