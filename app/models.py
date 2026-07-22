"""SQLAlchemy ORM 모델.

엔티티 정식 키는 corp_code(8자리)다(AD-5). stock_code(6자리)는 company 속성.
시가총액은 company에 두지 않는다(AD-9, 시총 단일원천=prices/KRX, Story 1.3).

Story 1.2: Company, Financial 추가.
후속: prices / valueup_plan / ownership / macro_indicator / valueup_score / mna_score.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """모든 ORM 모델의 공통 Base."""

    pass


class Company(Base):
    """상장사 기본정보 (writer = dart_adapter, AD-3/AD-9)."""

    __tablename__ = "company"
    __table_args__ = (
        CheckConstraint("length(corp_code) = 8", name="ck_company_corp_code_len"),
    )

    corp_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    stock_code: Mapped[str | None] = mapped_column(String(6), index=True)
    corp_name: Mapped[str] = mapped_column(String(200))
    market: Mapped[str | None] = mapped_column(String(10))  # KOSPI / KOSDAQ
    sector: Mapped[str | None] = mapped_column(String(100))


class Financial(Base):
    """분기 재무제표 원천 (writer = dart_adapter). 자연키 (corp_code, year, quarter), AD-7."""

    __tablename__ = "financials"
    __table_args__ = (
        UniqueConstraint("corp_code", "year", "quarter", name="uq_fin_corp_year_q"),
        CheckConstraint("quarter BETWEEN 1 AND 4", name="ck_fin_quarter"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    year: Mapped[int] = mapped_column()
    quarter: Mapped[int] = mapped_column()  # 1~4
    fs_div: Mapped[str | None] = mapped_column(String(3))  # CFS(연결) / OFS(개별)

    # 손익
    revenue: Mapped[int | None] = mapped_column(BigInteger)
    net_income: Mapped[int | None] = mapped_column(BigInteger)
    operating_income: Mapped[int | None] = mapped_column(BigInteger)
    depreciation: Mapped[int | None] = mapped_column(BigInteger)
    # 재무상태
    equity: Mapped[int | None] = mapped_column(BigInteger)
    total_assets: Mapped[int | None] = mapped_column(BigInteger)
    total_liabilities: Mapped[int | None] = mapped_column(BigInteger)
    cash: Mapped[int | None] = mapped_column(BigInteger)
    total_debt: Mapped[int | None] = mapped_column(BigInteger)
    # 환원 (별도 공시 기반, best-effort; 없으면 null)
    dividend_total: Mapped[int | None] = mapped_column(BigInteger)
    # 자사주(1.8, tesstkAcqsDspsSttus): 취득/소각 수량(주) — 워싱 presence 신호(>0), KRW 액 아님
    buyback_amount: Mapped[int | None] = mapped_column(BigInteger)  # 자사주 취득 수량(주)
    buyback_retired_amount: Mapped[int | None] = mapped_column(BigInteger)  # 자사주 소각 수량(주)


class Price(Base):
    """일별 시세·시가총액 원천 (writer = krx_adapter). 시총 단일원천(AD-9). 자연키 (corp_code, date)."""

    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint("corp_code", "date", name="uq_prices_corp_date"),
        CheckConstraint(
            "(close IS NULL OR close >= 0) AND (volume IS NULL OR volume >= 0) "
            "AND (trading_value IS NULL OR trading_value >= 0) "
            "AND (market_cap IS NULL OR market_cap >= 0)",
            name="ck_prices_nonneg",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    date: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD (KST)
    close: Mapped[int | None] = mapped_column(BigInteger)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    trading_value: Mapped[int | None] = mapped_column(BigInteger)  # 거래대금
    market_cap: Mapped[int | None] = mapped_column(BigInteger)  # 시가총액(AD-9 단일원천)


class ValueupPlan(Base):
    """밸류업 계획공시 원천 (writer = dart_adapter, AD-3). 자연키 (corp_code, disclosure_date), AD-7.

    "기업가치 제고 계획"은 자유서식 공시 → 목표 필드는 best-effort 파싱(못 찾으면 null, NFR2).
    원문 raw_text는 항상 보존(재파싱 가능). 목표 지표는 비율/배수라 Float.
    """

    __tablename__ = "valueup_plan"
    __table_args__ = (
        UniqueConstraint("corp_code", "disclosure_date", name="uq_valueup_corp_date"),
    )

    plan_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    disclosure_date: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD (접수일)
    # 목표치 (best-effort 파싱, 없으면 null)
    target_roe: Mapped[float | None] = mapped_column(Float)  # %
    target_payout_ratio: Mapped[float | None] = mapped_column(Float)  # 배당성향 %
    # 총주주환원율(배당+자사주매입)/순이익 % — **배당성향과 다른 지표**(5-1).
    # 실데이터상 기업 다수가 배당성향이 아니라 이쪽으로 약속한다(공시 60건 중 17건).
    # 한 필드에 섞으면 목표와 실적의 정의가 어긋나므로 분리해서 받는다.
    target_total_return_ratio: Mapped[float | None] = mapped_column(Float)
    target_pbr: Mapped[float | None] = mapped_column(Float)  # 배
    period_start: Mapped[str | None] = mapped_column(String(10))  # 목표기간 시작(연도/ISO)
    period_end: Mapped[str | None] = mapped_column(String(10))  # 목표기간 종료
    buyback_planned: Mapped[bool | None] = mapped_column(Boolean)  # 자사주 계획 언급 여부
    raw_text: Mapped[str | None] = mapped_column(Text)  # 공시 원문(항상 보존)


class Ownership(Base):
    """지분구조 원천 (writer = dart_adapter, AD-3). 자연키 (corp_code, as_of), AD-7.

    최대주주 지분율(보통주 기준 최대주주+특수관계인 합계)·자사주 비중. M&A 엔진(2.3)의
    지배구조 취약성 입력(AD-10). 미공시·계정 누락 시 해당 필드 null(NFR2).
    """

    __tablename__ = "ownership"
    __table_args__ = (
        UniqueConstraint("corp_code", "as_of", name="uq_ownership_corp_asof"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    as_of: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD (기준일)
    largest_shareholder_pct: Mapped[float | None] = mapped_column(Float)  # % (보통주)
    treasury_stock_pct: Mapped[float | None] = mapped_column(Float)  # 자사주/발행총수 %


class MacroIndicator(Base):
    """매크로 지표 시계열 (writer = ecos_adapter, AD-3). 종목 무관. 자연키 (indicator, date)."""

    __tablename__ = "macro_indicator"
    __table_args__ = (
        UniqueConstraint("indicator", "date", name="uq_macro_indicator_date"),
        CheckConstraint(
            "indicator IN ('base_rate','bond_3y','usd_krw','leading_index')",
            name="ck_macro_indicator_allowed",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    indicator: Mapped[str] = mapped_column(String(30), index=True)  # base_rate 등
    date: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD
    value: Mapped[float | None] = mapped_column(Float)
    frequency: Mapped[str | None] = mapped_column(String(1))  # M(월)/D(일) — look-ahead 판별용


class ValueupScore(Base):
    """Value-up 갭 스코어 (writer = gap_engine, AD-4). 자연키 (corp_code, as_of), AD-8.

    achievement_rate·progress_rate·execution_score·washing_flag는 계산 불가(입력 애매/누락)
    시 null(NFR2, "null > 틀린 값"). washing_flag는 특히 null을 False로 강제하지 않는다
    (null=판단불가, scoring.md 2026-07-10 강화). Boolean 컬럼 전부 nullable — null 전파 필수.
    """

    __tablename__ = "valueup_score"
    __table_args__ = (
        UniqueConstraint("corp_code", "as_of", name="uq_valueup_score_corp_asof"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    as_of: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD (progress_rate의 today)
    # 목표·실제·갭(2.4 표시용, 엔진 계산 시점 동결 — 서빙 재계산 시 as_of 정합 깨짐 방지)
    target_roe: Mapped[float | None] = mapped_column(Float)
    actual_roe: Mapped[float | None] = mapped_column(Float)
    roe_gap: Mapped[float | None] = mapped_column(Float)  # actual − target(둘 다 있을 때만)
    achievement_rate: Mapped[float | None] = mapped_column(Float)  # actual_roe/target_roe
    progress_rate: Mapped[float | None] = mapped_column(Float)  # 연도 단위, [0,1] 클램프
    execution_score: Mapped[float | None] = mapped_column(Float)  # 0~100
    washing_flag: Mapped[bool | None] = mapped_column(Boolean)
    buyback_executed: Mapped[bool | None] = mapped_column(Boolean)
    buyback_retired: Mapped[bool | None] = mapped_column(Boolean)
    buyback_status: Mapped[str | None] = mapped_column(String(20))  # retired/purchased_only/none/unknown
    # execution_score가 **어떤 약속을 기준으로** 채점됐는지(5-1). 예: 'return+buyback'.
    # 기업이 공시한 항목만으로 채점하므로 가중치 기반이 종목마다 다르다 — 그 사실을
    # 숨기면 점수를 종목 간 비교에 잘못 쓰게 된다(mna의 population_basis와 같은 이유).
    score_basis: Mapped[str | None] = mapped_column(String(40))


class MnaScore(Base):
    """M&A Target Score (writer = mna_engine, AD-10). 자연키 (corp_code, as_of).

    cross-sectional 백분위(시장 내 상대 순위) 기반 — 요소 서브지표가 하나라도 null이면
    요소 점수 null, 요소가 하나라도 null이면 mna_target_score null(엄격, 리드 결정 2026-07-10).
    macro_score는 종목 무관 공통값(as_of당 1회 계산).
    """

    __tablename__ = "mna_score"
    __table_args__ = (
        UniqueConstraint("corp_code", "as_of", name="uq_mna_score_corp_asof"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    as_of: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD
    mna_target_score: Mapped[float | None] = mapped_column(Float)  # 0~100
    valuation_score: Mapped[float | None] = mapped_column(Float)  # 0~1 (저평가)
    capacity_score: Mapped[float | None] = mapped_column(Float)  # 0~1 (인수여력)
    ownership_score: Mapped[float | None] = mapped_column(Float)  # 0~1 (지배구조 취약성)
    macro_score: Mapped[float | None] = mapped_column(Float)  # 0~1, 종목 무관 공통
    # 백분위 모집단 식별(2.7): sector:{KSIC2} / market_fallback(peer 미달) / market(sector 없음)
    population_basis: Mapped[str | None] = mapped_column(String(20))
