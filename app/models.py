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
    Integer,
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
    # DART 접수번호(14자리, 선행 0 있음 → 문자열). **출처 추적의 최소 단위**:
    # 이 값이 있어야 DART 뷰어·첨부 목록 URL을 조립할 수 있다. 수집기가 document.xml을
    # 부를 때 이미 갖고 있던 값인데 저장하지 않아 첨부 수집의 1차 관문이 막혀 있었다.
    # null = 이 컬럼 신설(0015) 이전에 적재된 행 — 재수집해야 채워진다.
    rcept_no: Mapped[str | None] = mapped_column(String(14), index=True)
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
    # 범위로 공시한 목표의 원문(0023, P1-2). "roe:11~13,payout_ratio:30~40" 형식.
    # 값 자체는 **하한**을 target_*에 넣는다(회사가 확실히 약속한 것은 하한이므로).
    # 하한만 보면 "11~13%로 약속한 회사"와 "11%로 약속한 회사"가 같아 보이고, 전자는
    # 달성 판정이 관대해진 상태다 — 그 사실을 감추지 않으려고 원문 범위를 남긴다.
    target_ranges: Mapped[str | None] = mapped_column(String(200))
    raw_text: Mapped[str | None] = mapped_column(Text)  # 공시 원문(항상 보존)
    # 본문이 **왜** 우리 축을 못 채웠는가(0018). axis_targets / other_metric / refiling /
    # no_targets. "미공시"와 "다른 지표로 공시"와 "다른 공시를 가리킴"은 서로 다른 사실이고,
    # 한 칸에 뭉치면 화면이 LG엔솔(매출·EBITDA로 명확히 공시)을 부실 공시로 보이게 한다.
    body_signal: Mapped[str | None] = mapped_column(String(24))
    # refiling일 때 가리킨 공시일. 못 읽으면 null(추측하지 않는다).
    body_reference_date: Mapped[str | None] = mapped_column(String(10))
    # 공시의 '관련 웹페이지' 필드가 가리킨 URL(0019). DART 첨부 경로가 닫힌 뒤 남은 길이며,
    # 회사가 규제 공시에서 스스로 지목한 주소다. 실측 49/60 공시가 담고 있다.
    related_url: Mapped[str | None] = mapped_column(String(500))


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


class PlanAttachment(Base):
    """밸류업 계획 **첨부(PDF)** 원천 (writer = attachment ingest, 0017).

    valueup_plan(본문)의 형제다. 같은 행에 섞지 않는 이유: valueup_plan upsert는
    "재파싱 결과가 권위 → null 포함 전체 교체"라, 본문 재수집 한 번에 첨부 파싱 결과가
    통째로 날아간다. 두 원천은 수명주기가 다르다.

    ⚠ 취득은 자동화하지 않는다 — DART robots.txt가 뷰어·첨부·PDF 다운로드 경로를 전부
    Disallow한다(2026-07-29 확인). 파일은 사람이 받아 attachments/에 두고, 코드는 읽기만
    한다. acquired_by가 그 사실을 데이터에 남긴다.
    """

    __tablename__ = "plan_attachment"
    __table_args__ = (
        UniqueConstraint("plan_id", "filename", name="uq_plan_attachment_plan_file"),
    )

    attachment_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, index=True)
    corp_code: Mapped[str] = mapped_column(String(8), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))  # 재파싱 멱등성 기준
    page_count: Mapped[int | None] = mapped_column(Integer)
    acquired_by: Mapped[str] = mapped_column(String(20), default="manual")
    # ir_site로 받았을 때의 정확한 출처 URL(0019). 같은 파일을 다시 받을 때 어디로
    # 가야 하는지도 여기 있다.
    source_url: Mapped[str | None] = mapped_column(String(500))
    acquired_at: Mapped[str | None] = mapped_column(String(10))
    parsed_at: Mapped[str | None] = mapped_column(String(10))
    target_roe: Mapped[float | None] = mapped_column(Float)
    target_payout_ratio: Mapped[float | None] = mapped_column(Float)
    target_total_return_ratio: Mapped[float | None] = mapped_column(Float)
    target_pbr: Mapped[float | None] = mapped_column(Float)
    period_start: Mapped[str | None] = mapped_column(String(10))
    period_end: Mapped[str | None] = mapped_column(String(10))
    buyback_planned: Mapped[bool | None] = mapped_column(Boolean)
    # 필드 → 근거 페이지({"target_roe": 7}). "첨부 PDF p.7"을 화면에 쓰기 위한 것.
    evidence_json: Mapped[str | None] = mapped_column(Text)
    # 파싱 실패를 조용히 null로 넘기지 않는다 — 왜 못 읽었는지 남긴다.
    parse_error: Mapped[str | None] = mapped_column(String(200))
    extracted_text: Mapped[str | None] = mapped_column(Text)  # 원문 보존(재파싱 가능)
    # OCR 층(0020). OCR을 적용한 페이지 목록(JSON) — evidence_json과 대조하면 어떤 값이
    # OCR 유래인지 재구성된다. OCR 유래 목표가 있으면 needs_review=True로 적재되고,
    # 사람이 승인(review_attachment CLI)하기 전에는 merge_attachment가 채점에 태우지
    # 않는다. 첫 실측에서 OCR+파서가 이행 실적을 목표로 오인했다 — 틀린 non-null은
    # null보다 위험하다.
    ocr_pages: Mapped[str | None] = mapped_column(Text)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(50))
    reviewed_at: Mapped[str | None] = mapped_column(String(10))
    review_note: Mapped[str | None] = mapped_column(String(300))


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
    # 소각이 **약속 전인가 후인가**(0022, P1-4). buyback_status는 "무엇을 했나"만 답하고
    # 계획과 무관하다 — 이 컬럼이 "언제 했나"를 잰다.
    # in_period/outside_period(기간 기준) · after_disclosure/before_disclosure(공시일 기준)
    # · same_year_unknown(같은 해, 분기 미상이라 판정 불가) · null(소각 없음·근거 부족).
    # 어느 자로 쟀는지를 값 자체가 말한다(basis 별도 컬럼 없음).
    buyback_timing: Mapped[str | None] = mapped_column(String(20))
    # execution_score가 **어떤 약속을 기준으로** 채점됐는지(5-1). 예: 'return+buyback'.
    # 기업이 공시한 항목만으로 채점하므로 가중치 기반이 종목마다 다르다 — 그 사실을
    # 숨기면 점수를 종목 간 비교에 잘못 쓰게 된다(mna의 population_basis와 같은 이유).
    score_basis: Mapped[str | None] = mapped_column(String(40))
    # 채점에서 **제외된** 축과 사유(0021). score_basis(포함된 축)의 여집합.
    # "roe:no_period" = 계획 기간 미상이라 진척 대비 달성을 말할 수 없어 ROE 축을 뺐다.
    # 빼되 숨기지 않는다 — 못 잰 축이 조용히 사라지면 점수가 실제보다 완전해 보인다.
    excluded_axes: Mapped[str | None] = mapped_column(String(100))
    # 이 점수가 실제로 근거로 삼은 valueup_plan(0016). 서빙이 "최신 공시" 규칙을 **재현하지
    # 않고** 이 id로 조인하게 하려는 것 — 규칙이 엔진과 서빙 두 곳에 있으면 어긋나는 순간
    # 화면이 실제 근거가 아닌 공시를 출처로 표시한다(출처 표기의 목적과 정반대).
    # null = 0016 이전 채점분(재채점해야 채워짐).
    source_plan_id: Mapped[int | None] = mapped_column(Integer)


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


class OpacityScore(Base):
    """공시 불투명도 순위 (writer = opacity_engine). 자연키 (corp_code, as_of).

    MnaScore 형제 — 둘 다 **cross-sectional 백분위**(peer 대비 상대 위치가 곧 점수)라
    세대가 섞이면 순위 자체가 무의미해진다. washing_flag를 대체하되, valueup_score(종목별
    절대 측정치)에 컬럼으로 얹지 않고 별도 테이블로 두는 이유가 이 성질이다(파티 결정
    2026-07-23). '고의(워싱)'를 판정하지 않고 **공시하지 않은 목표 축의 수**를 peer 대비
    백분위로 드러낸다(opacity_engine 참조). 표지 통지문(첨부 참조·본문 전무)은 순위 불가로
    행을 만들지 않는다 — opacity_rank/count/basis 전부 그 종목엔 없다(모집단에서도 제외).
    """

    __tablename__ = "opacity_score"
    __table_args__ = (
        UniqueConstraint("corp_code", "as_of", name="uq_opacity_score_corp_asof"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(
        String(8), ForeignKey("company.corp_code"), index=True
    )
    as_of: Mapped[str] = mapped_column(String(10))  # ISO YYYY-MM-DD
    opacity_rank: Mapped[float | None] = mapped_column(Float)  # 0~1, 높을수록 불투명
    opacity_count: Mapped[int | None] = mapped_column(Integer)  # 미공시 축 수(0~4)
    # 백분위 모집단 식별(mna의 population_basis와 동일 규약): sector:{KSIC2}/market_fallback/market
    opacity_basis: Mapped[str | None] = mapped_column(String(20))
