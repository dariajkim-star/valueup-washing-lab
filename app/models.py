"""SQLAlchemy ORM 모델.

엔티티 정식 키는 corp_code(8자리)다(AD-5). stock_code(6자리)는 company 속성.
시가총액은 company에 두지 않는다(AD-9, 시총 단일원천=prices/KRX, Story 1.3).

Story 1.2: Company, Financial 추가.
후속: prices / valueup_plan / ownership / macro_indicator / valueup_score / mna_score.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    String,
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
    buyback_amount: Mapped[int | None] = mapped_column(BigInteger)  # 자사주 매입액
    buyback_retired_amount: Mapped[int | None] = mapped_column(BigInteger)  # 소각액


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
