# 기술 스택 & 구현 규약 (HOW)

> SPEC-valueup-washing companion. 캡의 intent(WHAT)를 실현하는 구현 방식. SPEC 본문은 HOW를 담지 않는다.

## 스택

| 층 | 선택 | 비고 |
|---|---|---|
| API | FastAPI + Uvicorn | OpenAPI 자동 문서 `/docs` |
| ORM/DB | SQLAlchemy 2.0 + PostgreSQL | 개발 폴백 SQLite |
| 마이그레이션 | alembic | 테이블만; `valuation_metrics` 뷰는 마이그레이션 내 raw SQL |
| 수집 | requests(OpenDART REST — 재무·공시·지분), pykrx(KRX), requests(ECOS OpenAPI) | dart-fss 대신 REST 직접 호출(빠르고 견고) |
| 분석 | pandas, numpy | Value-up 갭 + M&A 스코어 산출 |
| 배치 | APScheduler | 일배치 + 수동 트리거 `POST /ingest/run` |
| 설정 | pydantic-settings | `.env`: DART_API_KEY, ECOS_API_KEY, 워싱 임계치·Value-up/M&A 가중치 |
| 프론트 | React 19.2 + Vite 8.1 + TypeScript | 애널리스트 스크리너 SPA |
| 프론트 라이브러리 | TanStack Query(서버상태)·TanStack Table(그리드)·Recharts(차트)·shadcn-ui+Tailwind | |
| 테스트 | pytest, httpx | |

## 폴더 구조

```
valueup-washing-lab/
├── app/
│   ├── main.py            # FastAPI 엔트리
│   ├── config.py          # 설정 + 워싱 임계치/가중치 (scoring.md 파라미터)
│   ├── db.py              # 세션/엔진
│   ├── models.py          # SQLAlchemy 모델
│   ├── schemas.py         # pydantic 응답 스키마
│   ├── routers/           # companies / metrics / valueup / mna / financials / stats
│   ├── ingest/            # dart.py, krx.py, ecos.py, scheduler.py
│   └── analysis/          # gap_engine.py (Value-up), mna_engine.py (M&A)
├── alembic/               # 마이그레이션 (뷰 DDL 포함)
├── tests/
└── requirements.txt
```

## 규약

- `valuation_metrics`는 SQLAlchemy 모델이 아니라 **읽기 전용 뷰**로 매핑한다(→ db-schema.md의 DDL).
- 종목코드(6자리) ↔ corp_code(8자리)는 `company` 테이블에서 매핑 후 조인한다.
- API 응답은 목록형이면 `{items, total, page, size}` 봉투를 따른다.
- 산출물 시각화: Tableau(밸류업 점수·업종 저평가 맵·ROE-PBR 산점도·배당/자사주) + Figma(애널리스트 스크리너 UI). 코드 산출물은 이들이 물릴 정제 API/뷰까지.
