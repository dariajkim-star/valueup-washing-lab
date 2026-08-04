"""Story 1.2 — DART 어댑터 정규화·멱등 upsert 검증 (라이브 키 없이 fixture)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.ingest.dart import DartAdapter, DartAdapterError
from app.models import Base, Financial
from tests.fixtures import DART_RAW_SAMSUNG


def settings_has_key() -> bool:
    return bool(settings.dart_api_key.get_secret_value())


@pytest.fixture()
def session() -> Session:
    """인메모리 SQLite 세션(외부 DB 불필요)."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_normalize_maps_accounts() -> None:
    """AC2/AC4: 계정명이 컬럼으로 매핑되고, 누락 계정은 null."""
    company, fins = DartAdapter().normalize(DART_RAW_SAMSUNG)
    assert company["corp_code"] == "00126380"
    assert company["market"] == "KOSPI"
    assert len(fins) == 1
    rec = fins[0]
    assert rec["revenue"] == 70_000_000_000_000
    assert rec["net_income"] == 8_000_000_000_000
    assert rec["equity"] == 300_000_000_000_000
    # 누락 계정 → null (NFR2)
    assert rec["depreciation"] is None
    assert rec["total_debt"] is None
    assert rec["buyback_amount"] is None
    assert rec["buyback_retired_amount"] is None
    assert rec["dividend_total"] == 2_000_000_000_000


def test_upsert_is_idempotent(session: Session) -> None:
    """AC3: 같은 배치 2회 실행해도 (corp_code,year,quarter) 중복 행 없음."""
    adapter = DartAdapter()
    records = adapter.normalize(DART_RAW_SAMSUNG)

    adapter.upsert(session, records)
    session.commit()
    adapter.upsert(session, records)  # 재실행
    session.commit()

    count = session.scalar(select(func.count()).select_from(Financial))
    assert count == 1  # 중복 없음


def test_upsert_updates_values(session: Session) -> None:
    """AC3: 재실행 시 값이 갱신된다(새 행 추가 아님)."""
    adapter = DartAdapter()
    company, fins = adapter.normalize(DART_RAW_SAMSUNG)
    adapter.upsert(session, (company, fins))
    session.commit()

    fins[0]["net_income"] = 9_999_999_999_999  # 값 변경 후 재적재
    adapter.upsert(session, (company, fins))
    session.commit()

    obj = session.scalars(select(Financial)).one()
    assert obj.net_income == 9_999_999_999_999


def test_fetch_without_key_raises(monkeypatch) -> None:
    """AC5: DART_API_KEY 미설정 시 명확한 에러."""
    from app.config import settings
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "dart_api_key", SecretStr(""))
    with pytest.raises(DartAdapterError, match="DART_API_KEY"):
        DartAdapter().fetch("00126380", "2024")


def test_parse_amount() -> None:
    """금액 파싱: 콤마·회계음수(괄호·△·유니코드 마이너스)·빈값."""
    from app.ingest.dart import _parse_amount

    assert _parse_amount("514,531,948,000,000") == 514_531_948_000_000
    assert _parse_amount("-3,000") == -3000
    assert _parse_amount("(3,000)") == -3000  # 회계 괄호 음수
    assert _parse_amount("△3,000") == -3000  # 삼각형 음수
    assert _parse_amount("−3,000") == -3000  # 유니코드 마이너스
    assert _parse_amount("") is None
    assert _parse_amount("-") is None
    assert _parse_amount(None) is None
    assert _parse_amount("abc") is None


def test_sum_debt_handles_duplicate_labels() -> None:
    """총차입금은 '모든 차입 행' 합산 — 같은 '차입금'이 유동/비유동 중복(하이닉스)도 합산."""
    from app.ingest.dart import _sum_debt

    # 하이닉스식: '차입금'이 두 번(유동 5.25조 + 비유동 17.43조) + 리스부채 2회
    rows = [
        {"account_nm": "차입금", "thstrm_amount": "5,252,238,000,000"},
        {"account_nm": "리스부채", "thstrm_amount": "588,355,000,000"},
        {"account_nm": "차입금", "thstrm_amount": "17,431,495,000,000"},
        {"account_nm": "리스부채", "thstrm_amount": "2,180,021,000,000"},
        {"account_nm": "자산총계", "thstrm_amount": "119,855,209,000,000"},  # 무시
    ]
    assert _sum_debt(rows) == 25_452_109_000_000
    assert _sum_debt([{"account_nm": "자산총계", "thstrm_amount": "100"}]) is None


def test_sum_debt_matches_ifrs_tags_and_excludes_cash_flow() -> None:
    """[2026-07-31] 표준 태그로 잡고, **현금흐름표 항목은 제외**한다.

    실측(라이브 DART): 현대모비스의 차입 계정은 "유동 차입금 및 비유동차입금(사채 포함)의
    유동성 대체 부분 합계"처럼 회사마다 문구가 달라 라벨 완전일치로는 못 잡았다(커버리지
    67.5%). 그런데 같은 응답에 "장기차입금의 상환" 같은 **현금흐름** 항목이 있어, 부분일치로
    넓히면 잔액에 유출입을 더한 틀린 값이 나온다. sj_div='BS' 한정이 그 방어다.
    """
    from app.ingest.dart import _sum_debt

    rows = [
        # 재무상태표 — 표준 태그로 매칭(한글 문구는 회사마다 다름)
        {"sj_div": "BS", "account_id": "ifrs-full_LongtermBorrowings",
         "account_nm": "비유동차입금(사채 포함)의 비유동성 부분", "thstrm_amount": "1,927,485,000,000"},
        {"sj_div": "BS", "account_id": "ifrs-full_CurrentLeaseLiabilities",
         "account_nm": "유동성리스부채", "thstrm_amount": "145,865,000,000"},
        # 표준계정코드 미사용(삼성전자 형태) — 한글 라벨 완전일치로 구제
        {"sj_div": "BS", "account_id": "-표준계정코드 미사용-",
         "account_nm": "단기차입금", "thstrm_amount": "1,000,000"},
        # 현금흐름표 — 잔액이 아니라 유출입이므로 절대 더하면 안 된다
        {"sj_div": "CF", "account_id": "ifrs-full_RepaymentsOfBorrowings",
         "account_nm": "장기차입금의 상환", "thstrm_amount": "999,999,999,999"},
        {"sj_div": "BS", "account_id": "ifrs-full_Assets",
         "account_nm": "자산총계", "thstrm_amount": "119,855,209,000,000"},  # 무시
    ]
    assert _sum_debt(rows) == 1_927_485_000_000 + 145_865_000_000 + 1_000_000


def test_sum_debt_keeps_working_without_sj_div() -> None:
    """sj_div가 없는 응답(구형·픽스처)에서는 필터를 적용하지 않는다 — 통째로 날리지 않게."""
    from app.ingest.dart import _sum_debt

    assert _sum_debt([{"account_nm": "차입금", "thstrm_amount": "100"}]) == 100


def test_collect_accounts_revenue_tag_fallback() -> None:
    """[2026-08-03 P1-6a] 라벨이 '매출'이면 ifrs-full_Revenue 태그로 잡는다.

    실측(라이브 DART): LG CNS·한일홀딩스·한전기술 등 6개사의 손익 계정명이 '매출'
    ('총 수익' 변형 포함)이라 라벨 완전일치('매출액'·'영업수익')를 전부 비껴갔다 —
    ebitda_margin 결측으로 버킷 23·62가 시장 폴백. 태그는 IS/CIS 한정.
    """
    from app.ingest.dart import _ACCOUNT_MAP, _collect_accounts, _pick

    rows = [
        # LG CNS 형태: 계정명 '매출' — 라벨로는 못 잡고 태그로 잡는다
        {"sj_div": "IS", "account_id": "ifrs-full_Revenue",
         "account_nm": "매출", "thstrm_amount": "5,982,627,063,000"},
        # 하위 태그(공사매출)는 화이트리스트 밖 — 총계만 잡혀야 한다
        {"sj_div": "IS", "account_id": "ifrs-full_RevenueFromConstructionContracts",
         "account_nm": "공사매출", "thstrm_amount": "75,567,137,275"},
    ]
    accounts = _collect_accounts(rows)
    assert _pick(accounts, _ACCOUNT_MAP["revenue"]) == 5_982_627_063_000


def test_collect_accounts_equity_tag_fallback() -> None:
    """[2026-08-03 P1-6a] 한섬: 계정명 '자본 총계'(공백) — 완전일치 실패, 태그로 구제."""
    from app.ingest.dart import _ACCOUNT_MAP, _collect_accounts, _pick

    rows = [
        {"sj_div": "BS", "account_id": "ifrs-full_Equity",
         "account_nm": "자본 총계", "thstrm_amount": "1,406,099,400,780"},
    ]
    assert _pick(_collect_accounts(rows), _ACCOUNT_MAP["equity"]) == 1_406_099_400_780


def test_collect_accounts_assets_liabilities_tag_fallback() -> None:
    """[2026-08-03] 총계 라벨이 '자산 총계'(공백)·'총자산'·'자산'으로 갈린다 — 태그로 구제.

    실측(라이브 DART): LG화학·LG생활건강·한화솔루션 등 12개사 16행에서 부채총계가
    결측이었는데, 원문에는 ifrs-full_Assets·ifrs-full_Liabilities 총계 행이 있었다.
    라벨 완전일치('자산총계'·'부채총계')만 비껴간 것. debt_ratio 사망의 원인.
    """
    from app.ingest.dart import _ACCOUNT_MAP, _collect_accounts, _pick

    rows = [
        # LG화학 형태: 공백 있는 '자산 총계' / '부채 총계'
        {"sj_div": "BS", "account_id": "ifrs-full_Assets",
         "account_nm": "자산 총계", "thstrm_amount": "93,857,762,000,000"},
        {"sj_div": "BS", "account_id": "ifrs-full_Liabilities",
         "account_nm": "부채 총계", "thstrm_amount": "45,862,299,000,000"},
        # 자본과 부채의 합계(= 자산)는 별개 태그 — 화이트리스트 밖이라 섞이지 않는다
        {"sj_div": "BS", "account_id": "ifrs-full_EquityAndLiabilities",
         "account_nm": "부채와 자본 총계", "thstrm_amount": "93,857,762,000,000"},
    ]
    accounts = _collect_accounts(rows)
    assert _pick(accounts, _ACCOUNT_MAP["total_assets"]) == 93_857_762_000_000
    assert _pick(accounts, _ACCOUNT_MAP["total_liabilities"]) == 45_862_299_000_000


def test_collect_accounts_assets_tag_gated_by_statement() -> None:
    """자산·부채 태그는 BS 한정 — 다른 재무제표의 동일 태그는 주입하지 않는다."""
    from app.ingest.dart import _ACCOUNT_MAP, _collect_accounts, _pick

    rows = [
        {"sj_div": "CF", "account_id": "ifrs-full_Liabilities",
         "account_nm": "부채", "thstrm_amount": "999"},
    ]
    assert _pick(_collect_accounts(rows), _ACCOUNT_MAP["total_liabilities"]) is None


def test_zero_debt_evidence_gate() -> None:
    """[2026-08-04 리드 승인] 무차입 게이트 — 이자가 곧 반증이다.

    total_debt = 이자성 부채이므로 이자의 부재가 부채의 부재다. 실측: 결측 25개사 중
    이자 흔적 완전 0은 부국철강·SNT다이내믹스·SNT모티브 3곳뿐(전부 알려진 무차입).
    삼원강재(연 425만원)·한전KPS(5.2억)·카카오뱅크(이자비용 1.13조)는 null 유지.
    """
    from app.ingest.dart import _zero_debt_evidence

    base = [{"sj_div": "BS", "account_id": "ifrs-full_Liabilities",
             "account_nm": "부채총계", "thstrm_amount": "1,000"}]
    # 무차입 확정: BS 완결 + 차입 행 전무 + 이자 흔적 전무
    assert _zero_debt_evidence(base) is True
    # 이자 지급이 한 푼이라도 있으면 실격(삼원강재 425만원도 반증)
    assert _zero_debt_evidence(base + [
        {"sj_div": "CF", "account_nm": "이자의 지급", "thstrm_amount": "4,253,840"}]) is False
    # 이자비용도 반증(카카오뱅크형)
    assert _zero_debt_evidence(base + [
        {"sj_div": "IS", "account_nm": "이자비용", "thstrm_amount": "1,130,465,000,000"}]) is False
    # '금융부채' 총액형은 차입이 숨어 있을 수 있어 실격(한전형)
    assert _zero_debt_evidence(base + [
        {"sj_div": "BS", "account_nm": "유동금융부채", "thstrm_amount": "44,465,866,000,000"}]) is False
    # BS에 부채총계가 없으면(응답 잘림) 0 확정 불가
    assert _zero_debt_evidence([
        {"sj_div": "BS", "account_nm": "자산총계", "thstrm_amount": "1,000"}]) is False
    # 미지급이자·이자수익은 반증이 아니다 / 이자 행이 값 '-'면 반증이 아니다
    assert _zero_debt_evidence(base + [
        {"sj_div": "BS", "account_nm": "미지급이자", "thstrm_amount": "10"},
        {"sj_div": "IS", "account_nm": "이자수익", "thstrm_amount": "999"},
        {"sj_div": "CF", "account_nm": "이자지급", "thstrm_amount": "-"}]) is True


def test_collect_accounts_income_tag_fallback() -> None:
    """[2026-08-04] 순이익·영업이익 라벨 변형(로마숫자 접두·연결 접두) — 태그로 구제.

    실측 6곳: '연결당기순이익'(현대차)·'Ⅴ.당기순이익(손실)'(넷마블)·'XI. 당기순이익'
    (고려아연)·'당기연결순이익'(SKT) — 태그는 전부 ifrs-full_ProfitLoss.
    지배/비지배 귀속분은 ...AttributableTo... 별도 태그라 섞이지 않는다.
    """
    from app.ingest.dart import _ACCOUNT_MAP, _collect_accounts, _pick

    rows = [
        {"sj_div": "CIS", "account_id": "ifrs-full_ProfitLoss",
         "account_nm": "Ⅴ.당기순이익(손실)", "thstrm_amount": "3,216,188,118"},
        # 귀속분 — 화이트리스트 밖 태그라 총계를 오염시키지 않는다
        {"sj_div": "CIS", "account_id": "ifrs-full_ProfitLossAttributableToOwnersOfParent",
         "account_nm": "지배기업순손익", "thstrm_amount": "25,640,335,233"},
        {"sj_div": "CIS", "account_id": "dart_OperatingIncomeLoss",
         "account_nm": "Ⅲ.영업이익(손실)", "thstrm_amount": "215,627,215,188"},
    ]
    accounts = _collect_accounts(rows)
    assert _pick(accounts, _ACCOUNT_MAP["net_income"]) == 3_216_188_118
    assert _pick(accounts, _ACCOUNT_MAP["operating_income"]) == 215_627_215_188


def test_sum_debt_explicit_borrowing_label_variants() -> None:
    """[2026-08-04] 33개사 전수 조사의 '차입 명시' 변형 — 라벨은 공백 무시 정확일치.

    '유동금융부채'·'기타금융부채' 같은 총액·잡동사니 라벨은 **넣지 않는다**(한전 44조를
    차입금으로 적재하면 과대계상). 차입/사채/리스가 이름에 명시된 것만.
    """
    from app.ingest.dart import _sum_debt

    rows = [
        {"sj_div": "BS", "account_nm": "차입금 및 사채", "thstrm_amount": "100"},  # 공백 변형
        {"sj_div": "BS", "account_nm": "차입부채", "thstrm_amount": "50"},  # 메리츠·세아제강형
        {"sj_div": "BS", "account_nm": "유동성리스부채", "thstrm_amount": "5"},
        # 총액형은 매칭되면 안 된다
        {"sj_div": "BS", "account_nm": "유동금융부채", "thstrm_amount": "9,999"},
        {"sj_div": "BS", "account_nm": "기타금융부채", "thstrm_amount": "9,999"},
        # 새 태그(SBS 비유동차입금) — 이름이 목록 밖이라도 태그로 잡힌다
        {"sj_div": "BS", "account_id": "dart_LongTermBorrowingsGross",
         "account_nm": "비유동 차입금 등", "thstrm_amount": "30"},
    ]
    assert _sum_debt(rows) == 185


def test_collect_accounts_cash_tag_fallback_bs() -> None:
    """[2026-08-04] 비금융 2행: BS 라벨이 '현금 및 현금성자산'(공백) — 태그로 구제."""
    from app.ingest.dart import _ACCOUNT_MAP, _collect_accounts, _pick

    rows = [{"sj_div": "BS", "account_id": "ifrs-full_CashAndCashEquivalents",
             "account_nm": "현금 및 현금성자산", "thstrm_amount": "29,350,112,230"}]
    assert _pick(_collect_accounts(rows), _ACCOUNT_MAP["cash"]) == 29_350_112_230


def test_collect_accounts_cash_from_cf_period_end() -> None:
    """[2026-08-04] 금융 43행: BS엔 '현금및예치금'뿐 — CF의 '기말' 잔액으로 구제.

    현금및예치금(dart_CashAndDuefromBanks)은 예치금 포함이라 다른 개념이다(대신증권
    2.41조 vs 진짜 현금 1.27조). 연간보고서 CF의 기말 현금및현금성자산이 정답이고,
    같은 태그가 '기초' 행에 붙으면 전년 값이므로 이름 가드('기말')가 그것을 막는다.
    """
    from app.ingest.dart import _ACCOUNT_MAP, _collect_accounts, _pick

    rows = [
        # 예치금은 라벨도 태그도 화이트리스트 밖 — 절대 섞이면 안 된다
        {"sj_div": "BS", "account_id": "dart_CashAndDuefromBanks",
         "account_nm": "현금및예치금", "thstrm_amount": "2,406,632,887,000"},
        # 기초 행에 같은 태그가 붙어도 가드가 막는다(1년 오프바이원 방지)
        {"sj_div": "CF", "account_id": "ifrs-full_CashAndCashEquivalents",
         "account_nm": "기초현금및현금성자산", "thstrm_amount": "1,564,366,567,000"},
        # 기말 행 — '당기말의'·'분기말의'·'기말' 변형 전부 '기말'을 포함한다
        {"sj_div": "CF", "account_id": "ifrs-full_CashAndCashEquivalents",
         "account_nm": "당기말의 현금및현금성자산", "thstrm_amount": "1,267,694,740,000"},
    ]
    assert _pick(_collect_accounts(rows), _ACCOUNT_MAP["cash"]) == 1_267_694_740_000
    # 기초 행만 있으면(기말 행이 안 온 응답) 값을 만들지 않는다 — null > 전년 값
    only_begin = [rows[1]]
    assert _pick(_collect_accounts(only_begin), _ACCOUNT_MAP["cash"]) is None


def test_collect_accounts_label_wins_over_tag() -> None:
    """한글 라벨 완전일치가 태그보다 우선(_ACCOUNT_MAP 순서) — 기존 동작 불변."""
    from app.ingest.dart import _ACCOUNT_MAP, _collect_accounts, _pick

    rows = [
        {"sj_div": "IS", "account_id": "ifrs-full_Revenue",
         "account_nm": "매출액", "thstrm_amount": "100"},
    ]
    accounts = _collect_accounts(rows)
    assert _pick(accounts, _ACCOUNT_MAP["revenue"]) == 100


def test_collect_accounts_tag_gated_by_statement() -> None:
    """태그 매칭은 IS/CIS 한정 — 다른 재무제표의 동일 태그는 주입하지 않는다.

    (sj_div가 아예 없는 픽스처는 게이트 미적용 — _sum_debt와 동일 원칙.)
    """
    from app.ingest.dart import _ACCOUNT_MAP, _collect_accounts, _pick

    rows = [
        {"sj_div": "CF", "account_id": "ifrs-full_Revenue",
         "account_nm": "매출", "thstrm_amount": "999"},
    ]
    assert _pick(_collect_accounts(rows), _ACCOUNT_MAP["revenue"]) is None
    # sj_div 없는 구형 응답은 게이트 없이 잡는다
    rows_legacy = [
        {"account_id": "ifrs-full_Revenue", "account_nm": "매출", "thstrm_amount": "999"},
    ]
    assert _pick(_collect_accounts(rows_legacy), _ACCOUNT_MAP["revenue"]) == 999


def test_normalize_nulls_total_debt_when_exceeding_liabilities() -> None:
    """총차입금 > 총부채면 이중 합산 의심 — 틀린 값 대신 null(NFR2)."""
    from app.ingest.dart import DartAdapter

    raw = {
        "company": {"corp_code": "00000001", "corp_name": "테스트"},
        "periods": [
            {"year": 2025, "quarter": 4, "fs_div": "CFS",
             "accounts": {"부채총계": 1000}, "total_debt": 5000},
        ],
    }
    _, fins = DartAdapter().normalize(raw)
    assert fins[0]["total_liabilities"] == 1000
    assert fins[0]["total_debt"] is None  # 5000 > 1000 → 신뢰 불가


def test_normalize_uses_period_total_debt() -> None:
    """normalize는 fetch가 넘긴 period['total_debt']를 사용."""
    from app.ingest.dart import DartAdapter

    raw = {
        "company": {"corp_code": "00000001", "corp_name": "테스트"},
        "periods": [
            {"year": 2025, "quarter": 4, "fs_div": "CFS",
             "accounts": {"매출액": 100}, "total_debt": 3500},
        ],
    }
    _, fins = DartAdapter().normalize(raw)
    assert fins[0]["total_debt"] == 3500
    assert fins[0]["fs_div"] == "CFS"


def test_pick_falls_through_to_next_label() -> None:
    """첫 후보가 파싱 불가면 다음 후보를 본다."""
    from app.ingest.dart import _pick

    assert _pick({"매출액": "-", "수익(매출액)": 100}, ("매출액", "수익(매출액)")) == 100


def test_get_error_does_not_leak_key(monkeypatch) -> None:
    """_get 실패 시 예외 메시지에 API 키가 노출되지 않는다."""
    import requests

    from app.ingest.dart import DartAdapter, DartAdapterError

    adapter = DartAdapter()

    def _boom(*a, **k):
        raise requests.ConnectionError("boom http://x?crtfc_key=SECRETKEY")

    monkeypatch.setattr(adapter._session, "get", _boom)
    with pytest.raises(DartAdapterError) as ei:
        adapter._get("company.json", {"crtfc_key": "SECRETKEY"})
    assert "SECRETKEY" not in str(ei.value)


def test_fetch_rejects_bad_args(monkeypatch) -> None:
    """reprt_code·bsns_year 검증(fail-fast)."""
    from app.config import settings
    from pydantic import SecretStr

    from app.ingest.dart import DartAdapter, DartAdapterError

    monkeypatch.setattr(settings, "dart_api_key", SecretStr("k"))
    with pytest.raises(DartAdapterError, match="reprt_code"):
        DartAdapter().fetch("00126380", "2024", "99999")
    with pytest.raises(DartAdapterError, match="bsns_year"):
        DartAdapter().fetch("00126380", "20A4", "11011")


# ── Story 1.9: 배당총액 (alotMatter) ──

def test_buyback_amount_krw_reads_cash_flow() -> None:
    """[2026-08-04] 자사주 취득 '금액'은 자사주 표가 아니라 현금흐름표에 있다.

    tesstkAcqsDspsSttus에는 수량 칸만 있다(bsis_qy·change_qy_*·trmend_qy).
    실측 40곳 표본에서 계정명이 네 갈래로 갈렸고(아래), 태그는 그보다 더 흩어졌다.
    """
    from app.ingest.dart import _buyback_amount_krw

    for name in ("자기주식의 취득", "자기주식 취득", "자기주식 등의 취득",
                 "자기주식의 취득으로 인한 현금의 유출"):
        rows = [{"sj_div": "CF", "account_id": "dart_AcquisitionOfTreasuryShares",
                 "account_nm": name, "thstrm_amount": "820,000,000,000"}]
        assert _buyback_amount_krw(rows) == 820_000_000_000, name


def test_buyback_amount_krw_name_beats_tag() -> None:
    """계정명이 권위다 — 실측에 '자기주식의 취득'인데 태그가 **처분**인 행이 있었다.

    오전의 자산·부채 총계는 정반대였다(라벨이 갈려 태그로 구제). 열마다 권위가 다르다:
    재무상태표 총계는 태그, 현금흐름 항목은 이름.
    """
    from app.ingest.dart import _buyback_amount_krw

    mistagged = [{"sj_div": "CF",
                  "account_id": "ifrs-full_ProceedsFromSaleOrIssueOfTreasuryShares",
                  "account_nm": "자기주식의 취득", "thstrm_amount": "-396,885,000,000"}]
    assert _buyback_amount_krw(mistagged) == 396_885_000_000
    # 표준계정코드를 안 쓰는 회사도 이름으로 잡힌다(실측 40곳 중 4곳)
    untagged = [{"sj_div": "CF", "account_id": "-표준계정코드 미사용-",
                 "account_nm": "자기주식의 취득", "thstrm_amount": "151,682,000,000"}]
    assert _buyback_amount_krw(untagged) == 151_682_000_000


def test_buyback_amount_krw_excludes_non_returns() -> None:
    """제외 라벨이 규칙의 절반 — '취득' 부분일치만 하면 셋이 딸려 들어온다."""
    from app.ingest.dart import _buyback_amount_krw

    # 자회사 주식이지 우리 주주에게 간 돈이 아니다
    assert _buyback_amount_krw([{"sj_div": "CF", "account_nm": "종속기업의 자기주식 취득",
                                 "thstrm_amount": "1,000"}]) is None
    # 소각 '비용'은 취득이 아니다
    assert _buyback_amount_krw([{"sj_div": "CF", "account_nm": "자기주식의 소각 비용",
                                 "thstrm_amount": "1,000"}]) is None
    # 반대 방향
    assert _buyback_amount_krw([{"sj_div": "CF", "account_nm": "자기주식의 처분",
                                 "thstrm_amount": "1,000"}]) is None
    assert _buyback_amount_krw([{"sj_div": "CF",
                                 "account_nm": "자기주식의 처분 및 발행 현금흐름",
                                 "thstrm_amount": "1,000"}]) is None
    # 현금흐름표 밖의 동명 행은 잡지 않는다(자본변동표에 같은 이름이 온다)
    assert _buyback_amount_krw([{"sj_div": "SCE", "account_nm": "자기주식의 취득",
                                 "thstrm_amount": "1,000"}]) is None


def test_buyback_amount_krw_sign_and_absence() -> None:
    """부호 규약이 회사마다 갈려(양수 32·음수 1) 크기로 읽는다. 행이 없으면 None."""
    from app.ingest.dart import _buyback_amount_krw

    assert _buyback_amount_krw([{"sj_div": "CF", "account_nm": "자기주식의 취득",
                                 "thstrm_amount": "-136,699,000,000"}]) == 136_699_000_000
    assert _buyback_amount_krw([]) is None
    assert _buyback_amount_krw([{"sj_div": "CF", "account_nm": "배당금의 지급",
                                 "thstrm_amount": "100"}]) is None
    # 취득 행이 여럿이면 합산(신탁·직접취득이 따로 오는 회사)
    two = [
        {"sj_div": "CF", "account_nm": "자기주식의 취득", "thstrm_amount": "100"},
        {"sj_div": "CF", "account_nm": "자기주식 취득", "thstrm_amount": "-50"},
    ]
    assert _buyback_amount_krw(two) == 150


def test_normalize_zero_quantity_means_zero_amount() -> None:
    """취득 수량이 0으로 확정됐는데 CF에 취득 행이 없으면 금액도 0(결측 아님).

    두 표가 같은 말을 하고 있다. 반대로 수량>0인데 금액 행을 못 찾으면 null —
    매입은 했는데 액수를 모르는 상태를 0으로 세탁하지 않는다.
    """
    from app.ingest.dart import DartAdapter

    raw = {
        "company": {"corp_code": "00000001", "corp_name": "테스트"},
        "periods": [{
            "year": 2024, "quarter": 4, "accounts": {}, "total_debt": None,
            "buyback_amount_krw": None, "fs_div": "CFS",
            "buyback_rows": [{"acqs_mth1": "총계", "change_qy_acqs": "0",
                              "change_qy_incnr": "0"}],
            "dividend_rows": [],
        }],
    }
    _, fins = DartAdapter().normalize(raw)
    assert fins[0]["buyback_amount"] == 0
    assert fins[0]["buyback_amount_krw"] == 0

    raw["periods"][0]["buyback_rows"] = [{"acqs_mth1": "총계", "change_qy_acqs": "1,000",
                                          "change_qy_incnr": "0"}]
    _, fins = DartAdapter().normalize(raw)
    assert fins[0]["buyback_amount"] == 1000
    assert fins[0]["buyback_amount_krw"] is None


def test_dividend_total_scales_million_won() -> None:
    """AC2: '현금배당금총액(백만원)' 행 × 1,000,000 = KRW. 스케일 누락은 100만배 축소 오염."""
    from app.ingest.dart import _dividend_total

    rows = [
        {"se": "주당 현금배당금(원)", "stock_knd": "보통주", "thstrm": "361"},
        {"se": "현금배당금총액(백만원)", "thstrm": "2,452,153"},
        {"se": "현금배당성향(%)", "thstrm": "17.9"},
    ]
    assert _dividend_total(rows) == 2_452_153_000_000


def test_dividend_total_label_exact_match_only() -> None:
    """AC2: 라벨 정확일치(1-6 교훈) — 단위 미확인 변형은 값을 만들지 않고 null."""
    from app.ingest.dart import _dividend_total

    # 단위가 다른/없는 라벨 → 스케일을 확신할 수 없으므로 null
    assert _dividend_total([{"se": "현금배당금총액", "thstrm": "100"}]) is None
    assert _dividend_total([{"se": "현금배당금총액(억원)", "thstrm": "100"}]) is None
    # 주당배당금·성향만 있는 경우 → null
    assert _dividend_total([{"se": "주당 현금배당금(원)", "thstrm": "361"}]) is None


def test_dividend_total_none_and_negative_guard() -> None:
    """AC2/AC3: 미공시([])·미상(None)·음수(도메인 밖)는 null.

    ('-'는 2026-08-04부터 null이 아니라 0이다 — 아래 전용 테스트 참조.)
    """
    from app.ingest.dart import _dividend_total

    assert _dividend_total([]) is None
    assert _dividend_total(None) is None
    assert _dividend_total([{"se": "현금배당금총액(백만원)", "thstrm": "(500)"}]) is None
    # 총액 행 자체가 없으면 표가 그 말을 한 적이 없다 → null(0 아님)
    assert _dividend_total([{"se": "주당액면가액(원)", "thstrm": "5,000"}]) is None


def test_dividend_total_dash_is_zero_without_counter_evidence() -> None:
    """[2026-08-04] 총액 칸 '-'는 미공시가 아니라 **당기 무배당(0)**이다.

    실측: 결측 19곳 중 18곳이 이 형태였고, 그중 확인한 4곳은 주당배당금·배당수익률·
    배당성향까지 전 행이 '-'였다(전기엔 값이 있는 곳도 있다 — 배당 중단이지 미공시가 아니다).
    자사주 잔고와 같은 계열의 판단이되, 반증 재료가 **표 안에** 있어 순수 함수로 닫힌다.
    """
    from app.ingest.dart import _dividend_total

    rows = [
        {"se": "주당액면가액(원)", "thstrm": "5,000"},
        {"se": "현금배당금총액(백만원)", "thstrm": "-", "frmtrm": "9,274"},
        {"se": "주당 현금배당금(원)", "thstrm": "-", "frmtrm": "500"},
        {"se": "현금배당수익률(%)", "thstrm": "-", "frmtrm": "1.80"},
    ]
    assert _dividend_total(rows) == 0


def test_dividend_total_dash_stays_null_when_dividend_evidenced() -> None:
    """총액만 '-'이고 주당배당금·수익률이 양수면 **배당은 했다** → 0이 아니라 null.

    '안 줬다'와 '총액 칸만 비었다'를 섞으면 payout_ratio 0%가 사실이 아닌 채로 채점에 들어간다.
    수익률은 소수('3.10')라 정수 파서로는 못 읽어 _parse_ratio를 따로 둔다.
    """
    from app.ingest.dart import _dividend_total

    per_share = [
        {"se": "현금배당금총액(백만원)", "thstrm": "-"},
        {"se": "주당 현금배당금(원)", "stock_knd": "보통주식", "thstrm": "112"},
    ]
    assert _dividend_total(per_share) is None
    yield_only = [
        {"se": "현금배당금총액(백만원)", "thstrm": "-"},
        {"se": "현금배당수익률(%)", "stock_knd": "보통주식", "thstrm": "3.51"},
    ]
    assert _dividend_total(yield_only) is None


def test_dividend_total_refiling_latest_receipt_wins() -> None:
    """값 상충 1곳의 정체는 모순이 아니라 **재공시 두 벌**이었다 → 최신 접수번호 채택.

    실측(01363818): 25,026(2024-09-02 접수) vs 32,365(2025-03-12 접수). rcept_no를 보지
    않던 기존 로직은 '상충 → null'로 버렸다. 한 공시 안의 상충은 여전히 null이다.
    """
    from app.ingest.dart import _dividend_total

    rows = [
        {"rcept_no": "20240902000317", "se": "현금배당금총액(백만원)", "thstrm": "25,026"},
        {"rcept_no": "20250312000767", "se": "현금배당금총액(백만원)", "thstrm": "32,365"},
    ]
    assert _dividend_total(rows) == 32_365_000_000
    # 같은 공시 안에서 값이 갈리면 그건 재공시가 아니라 모순 → 확정 금지
    conflict = [
        {"rcept_no": "20250312000767", "se": "현금배당금총액(백만원)", "thstrm": "25,026"},
        {"rcept_no": "20250312000767", "se": "현금배당금총액(백만원)", "thstrm": "32,365"},
    ]
    assert _dividend_total(conflict) is None


def test_dividend_total_zero_is_zero() -> None:
    """공시했으나 배당 0 → 확정 0(null 아님) — 1.8 null vs 0 구분과 동일 계약."""
    from app.ingest.dart import _dividend_total

    assert _dividend_total([{"se": "현금배당금총액(백만원)", "thstrm": "0"}]) == 0


def test_normalize_fills_dividend_from_rows() -> None:
    """AC2: normalize가 period['dividend_rows']에서 dividend_total을 채운다(fixture=2조)."""
    company, fins = DartAdapter().normalize(DART_RAW_SAMSUNG)
    assert fins[0]["dividend_total"] == 2_000_000_000_000


# ── Story 1.8: 자기주식 취득/소각 (tesstkAcqsDspsSttus) ──

# 가짜 tesstkAcqsDspsSttus: 직접취득 3M주 취득 + 소각 1M주. 총계행 포함(이중집계 유발).
BUYBACK_ROWS = [
    {"acqs_mth1": "직접 취득", "acqs_mth2": "장내직접취득", "acqs_mth3": "-",
     "stock_knd": "보통주", "change_qy_acqs": "3,000,000",
     "change_qy_dsps": "0", "change_qy_incnr": "1,000,000"},
    {"acqs_mth1": "총계", "acqs_mth2": "-", "acqs_mth3": "-",
     "stock_knd": "보통주", "change_qy_acqs": "3,000,000",
     "change_qy_dsps": "0", "change_qy_incnr": "1,000,000"},  # 요약행 → 제외돼야
]


def test_buyback_totals_sums_leaf_excludes_summary() -> None:
    """AC2/AC3: leaf+총계 공존 시 이중가산 없음(총계가 권위 소스)."""
    from app.ingest.dart import _buyback_totals

    acqs, incnr = _buyback_totals(BUYBACK_ROWS)
    assert acqs == 3_000_000  # 6,000,000 아님(총계 이중가산 방지)
    assert incnr == 1_000_000


def test_buyback_totals_no_disclosure_is_none() -> None:
    """AC4: 미공시(빈 리스트) → (None, None). 기존값 안 덮게."""
    from app.ingest.dart import _buyback_totals

    assert _buyback_totals([]) == (None, None)


def test_buyback_totals_zero_activity_is_zero() -> None:
    """AC4: 공시했으나 활동 0(모든 change_qy='0') → 정수 0(>0=False), None 아님."""
    from app.ingest.dart import _buyback_totals

    rows = [{"acqs_mth1": "직접 취득", "acqs_mth2": "-", "acqs_mth3": "-",
             "change_qy_acqs": "0", "change_qy_incnr": "0"}]
    assert _buyback_totals(rows) == (0, 0)


def test_buyback_dash_only_field_is_zero_activity() -> None:
    """[2026-07-31 계약 변경] 칼럼은 왔는데 값이 '-'뿐이면 **0**(활동 없음)이다.

    이전엔 None(미상)이었다. 라이브 대조가 근거다 — 삼성전자·기아·경농이 모두 같은
    18행 표를 제출했고 차이는 수치 유무뿐이었다(삼성 6행·기아 3행에 값, 경농 0행).
    DART 표의 '-'는 "그 기간 해당 활동 없음"이지 미공시가 아니다.

    이전 계약의 대가: "자사주를 약속하고 실행하지 않은" 기업이 '판단 불가'로 처리돼
    execution_score가 통째로 죽었다(실측 28건). 워싱 신호가 미상으로 세탁된 셈이다.
    """
    from app.ingest.dart import _buyback_totals

    rows = [{"acqs_mth1": "직접 취득", "acqs_mth2": "-", "acqs_mth3": "-",
             "change_qy_acqs": "3,000,000", "change_qy_incnr": "-"}]
    assert _buyback_totals(rows) == (3_000_000, 0)


def test_buyback_missing_column_stays_unknown() -> None:
    """칼럼 자체가 없으면 여전히 None — '값이 없음'과 '칼럼이 안 옴'은 다르다."""
    from app.ingest.dart import _buyback_totals

    rows = [{"acqs_mth1": "직접 취득", "acqs_mth3": "-", "change_qy_acqs": "1,000"}]
    assert _buyback_totals(rows) == (1_000, None)  # incnr 칼럼 부재 → 미상 유지


def test_buyback_totals_summary_only_fallback() -> None:
    """AC3: leaf 없이 총계행만 오면 총계 사용(데이터 손실 방지)."""
    from app.ingest.dart import _buyback_totals

    rows = [{"acqs_mth1": "합계", "acqs_mth2": "-", "acqs_mth3": "-",
             "change_qy_acqs": "5,000,000", "change_qy_incnr": "2,000,000"}]
    assert _buyback_totals(rows) == (5_000_000, 2_000_000)


# ── 코드리뷰 patch 회귀 테스트 (2026-07-10, 자체+GPT 교차) ──

def test_buyback_per_field_total_backfill() -> None:
    """리뷰 High(GPT#1): 취득은 leaf, 소각은 총계에만 → 필드별 독립으로 둘 다 채움."""
    from app.ingest.dart import _buyback_totals

    rows = [
        {"acqs_mth1": "직접 취득", "change_qy_acqs": "3,000,000", "change_qy_incnr": "-"},
        {"acqs_mth1": "총계", "change_qy_acqs": "-", "change_qy_incnr": "1,000,000"},
    ]
    assert _buyback_totals(rows) == (3_000_000, 1_000_000)  # 이전엔 (3M, None) — 소각 유실


def test_buyback_duplicate_totals_agree_no_double() -> None:
    """리뷰 High(GPT#2): 합계+총계 중복 표기(값 일치) → 그 값, 이중가산 없음."""
    from app.ingest.dart import _buyback_totals

    rows = [
        {"acqs_mth1": "합계", "change_qy_acqs": "5,000,000", "change_qy_incnr": "0"},
        {"acqs_mth1": "총계", "change_qy_acqs": "5,000,000", "change_qy_incnr": "0"},
    ]
    assert _buyback_totals(rows) == (5_000_000, 0)  # 10,000,000 아님


def test_buyback_conflicting_totals_is_none() -> None:
    """리뷰 High(GPT#2/AC3): 상충하는 총계(5M vs 4M) → 애매 → null."""
    from app.ingest.dart import _buyback_totals

    rows = [
        {"acqs_mth1": "합계", "change_qy_acqs": "5,000,000"},
        {"acqs_mth1": "총계", "change_qy_acqs": "4,000,000"},
    ]
    assert _buyback_totals(rows) == (None, None)


def test_buyback_per_kind_totals_partition_sum() -> None:
    """총계가 주식종류별(보통주/우선주)로 나뉘면 파티션으로 보고 합산."""
    from app.ingest.dart import _buyback_totals

    rows = [
        {"acqs_mth1": "총계", "stock_knd": "보통주", "change_qy_acqs": "1,000,000"},
        {"acqs_mth1": "총계", "stock_knd": "우선주", "change_qy_acqs": "500,000"},
    ]
    assert _buyback_totals(rows)[0] == 1_500_000


def test_buyback_subtotal_only_is_none() -> None:
    """리뷰 High(GPT#3/AC3): 소계만 있으면(계층 검증 불가) 합산하지 않고 null."""
    from app.ingest.dart import _buyback_totals

    rows = [
        {"acqs_mth1": "직접 취득", "acqs_mth3": "-", "change_qy_acqs": "-"},
        {"acqs_mth1": "직접 취득", "acqs_mth3": "소계", "change_qy_acqs": "1,000,000"},
    ]
    assert _buyback_totals(rows) == (None, None)


def test_buyback_subtotal_plus_total_uses_total() -> None:
    """리뷰 High(GPT#2): 소계+총계 공존 → 총계만 사용(2M 아님)."""
    from app.ingest.dart import _buyback_totals

    rows = [
        {"acqs_mth3": "소계", "change_qy_acqs": "1,000,000"},
        {"acqs_mth1": "총계", "change_qy_acqs": "1,000,000"},
    ]
    assert _buyback_totals(rows)[0] == 1_000_000


def test_buyback_negative_quantity_rejected() -> None:
    """리뷰 High(GPT#4): 음수 표기(△·괄호)는 수량 도메인에 없음 → 해당 값 무시(상쇄 방지)."""
    from app.ingest.dart import _buyback_totals, _parse_quantity

    assert _parse_quantity("△1,000") is None
    assert _parse_quantity("(1,000)") is None
    assert _parse_quantity("1,000") == 1000
    rows = [
        {"acqs_mth1": "직접 취득", "change_qy_acqs": "3,000,000"},
        {"acqs_mth1": "직접 취득", "change_qy_acqs": "(3,000,000)"},  # 상쇄 시도
    ]
    assert _buyback_totals(rows)[0] == 3_000_000  # 0으로 상쇄되지 않음


def test_buyback_inner_space_label_is_total() -> None:
    """리뷰 Med: '총 계'(내부 공백 변형)도 총계로 분류 → leaf 오분류·이중가산 방지."""
    from app.ingest.dart import _buyback_totals

    rows = [
        {"acqs_mth1": "직접 취득", "change_qy_acqs": "3,000,000"},
        {"acqs_mth1": "총 계", "change_qy_acqs": "3,000,000"},
    ]
    assert _buyback_totals(rows)[0] == 3_000_000  # 6,000,000 아님


def test_buyback_malformed_rows_skipped() -> None:
    """리뷰 Med(GPT#10): 비dict 요소가 섞여도 크래시 없이 건너뜀."""
    from app.ingest.dart import _buyback_totals

    rows = ["garbage", 42, {"acqs_mth1": "직접 취득", "change_qy_acqs": "3,000,000"}]
    assert _buyback_totals(rows)[0] == 3_000_000


def _fake_get_factory(fail_buyback: bool = False, calls: list | None = None):
    """fetch 흐름 테스트용 가짜 _get(엔드포인트별 응답)."""
    def _fake_get(endpoint, params, allow_no_data=False):
        if calls is not None:
            calls.append(endpoint)
        if endpoint == "company.json":
            return {"status": "000", "corp_name": "테스트", "stock_code": "005930",
                    "corp_cls": "Y"}
        if endpoint == "fnlttSinglAcntAll.json":
            return {"status": "000",
                    "list": [{"account_nm": "매출액", "thstrm_amount": "100"}]}
        if endpoint == "tesstkAcqsDspsSttus.json":
            if fail_buyback:
                raise DartAdapterError("DART API 오류: status=020")
            return {"status": "000", "list": BUYBACK_ROWS}
        if endpoint == "alotMatter.json":  # 1.9 배당(기본: 미공시 013 → 빈 리스트)
            return {"list": []}
        raise AssertionError(f"unexpected endpoint: {endpoint}")
    return _fake_get


def test_fetch_buyback_failure_does_not_kill_financials(monkeypatch) -> None:
    """리뷰 High(GPT#6): buyback 호출 실패(쿼터 020 등)에도 재무 수집은 계속(degraded)."""
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "dart_api_key", SecretStr("k"))
    adapter = DartAdapter()
    monkeypatch.setattr(adapter, "_get", _fake_get_factory(fail_buyback=True))
    raw = adapter.fetch("00000001", "2024")
    assert len(raw["periods"]) == 1          # 재무 period 생존
    assert raw["periods"][0]["buyback_rows"] is None  # 실패 = 미상(None), 빈 리스트 아님
    assert raw["buyback_ok"] is False        # run.py가 degraded로 표시
    _, fins = adapter.normalize(raw)
    assert fins[0]["revenue"] == 100         # 재무는 정상 적재 경로
    assert fins[0]["buyback_amount"] is None  # 미상 → 기존값 안 덮음


def test_fetch_skips_buyback_when_no_accounts(monkeypatch) -> None:
    """리뷰 Med: 재무 데이터 없으면 buyback 호출 자체를 생략(rate-limit 낭비 방지)."""
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "dart_api_key", SecretStr("k"))
    adapter = DartAdapter()
    calls: list[str] = []

    def _no_accounts_get(endpoint, params, allow_no_data=False):
        calls.append(endpoint)
        if endpoint == "company.json":
            return {"status": "000", "corp_name": "테스트", "corp_cls": "Y"}
        return {"list": []}  # 재무 없음(013 상당)

    monkeypatch.setattr(adapter, "_get", _no_accounts_get)
    raw = adapter.fetch("00000001", "2024")
    assert raw["periods"] == []
    assert "tesstkAcqsDspsSttus.json" not in calls  # 호출 안 함
    assert raw["buyback_ok"] is True  # 미시도는 실패 아님


def test_fetch_include_buyback_false_skips_call(monkeypatch) -> None:
    """include_buyback=False면 tesstk 호출 생략(플래그 False 분기 커버)."""
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "dart_api_key", SecretStr("k"))
    adapter = DartAdapter()
    calls: list[str] = []
    monkeypatch.setattr(adapter, "_get", _fake_get_factory(calls=calls))
    raw = adapter.fetch("00000001", "2024", include_buyback=False)
    assert "tesstkAcqsDspsSttus.json" not in calls
    assert raw["periods"][0]["buyback_rows"] is None  # 미시도 = 미상


def test_get_non_dict_json_raises(monkeypatch) -> None:
    """리뷰 Med(GPT#10): 200이지만 JSON이 dict가 아니면 명확한 DartAdapterError."""
    adapter = DartAdapter()

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self):
            return ["not", "a", "dict"]

    monkeypatch.setattr(adapter._session, "get", lambda *a, **k: _Resp())
    with pytest.raises(DartAdapterError, match="형태 오류"):
        adapter._get("tesstkAcqsDspsSttus.json", {"crtfc_key": "k"})


def test_normalize_fills_buyback_from_rows() -> None:
    """AC2: normalize가 period['buyback_rows']에서 두 필드를 채운다."""
    raw = {
        "company": {"corp_code": "00000001", "corp_name": "테스트"},
        "periods": [
            {"year": 2025, "quarter": 4, "fs_div": "CFS",
             "accounts": {"매출액": 100}, "total_debt": None,
             "buyback_rows": BUYBACK_ROWS},
        ],
    }
    _, fins = DartAdapter().normalize(raw)
    assert fins[0]["buyback_amount"] == 3_000_000
    assert fins[0]["buyback_retired_amount"] == 1_000_000


def test_normalize_no_buyback_rows_is_none() -> None:
    """회귀: buyback_rows 없는 period(기존 fixture)는 두 필드 null."""
    _, fins = DartAdapter().normalize(DART_RAW_SAMSUNG)
    assert fins[0]["buyback_amount"] is None
    assert fins[0]["buyback_retired_amount"] is None


def test_upsert_buyback_none_safe(session: Session) -> None:
    """AC5: 이후 buyback None으로 재적재해도 기존 수량 보존(None-safe)."""
    adapter = DartAdapter()
    raw = {
        "company": {"corp_code": "00000001", "corp_name": "테스트"},
        "periods": [{"year": 2025, "quarter": 4, "fs_div": "CFS",
                     "accounts": {"매출액": 100}, "total_debt": None,
                     "buyback_rows": BUYBACK_ROWS}],
    }
    adapter.upsert(session, adapter.normalize(raw))
    session.commit()
    # 미공시로 재적재(buyback_rows 없음) → 기존 3M/1M 유지
    raw["periods"][0].pop("buyback_rows")
    adapter.upsert(session, adapter.normalize(raw))
    session.commit()
    obj = session.scalars(select(Financial)).one()
    assert obj.buyback_amount == 3_000_000  # 안 덮임
    assert obj.buyback_retired_amount == 1_000_000


def test_get_json_value_error_wrapped(monkeypatch) -> None:
    """T5: 비JSON 200(resp.json ValueError)도 DartAdapterError로 래핑(키 미노출)."""
    adapter = DartAdapter()

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            raise ValueError("No JSON could be decoded")

    monkeypatch.setattr(adapter._session, "get", lambda *a, **k: _Resp())
    with pytest.raises(DartAdapterError, match="DART 요청 실패") as ei:
        adapter._get("tesstkAcqsDspsSttus.json", {"crtfc_key": "SECRETKEY"})
    assert "SECRETKEY" not in str(ei.value)


@pytest.mark.skipif(
    not settings_has_key(), reason="DART_API_KEY 없음 — 라이브 테스트 스킵"
)
def test_live_fetch_samsung() -> None:
    """라이브: 삼성전자 실데이터가 매핑되는지(키 있을 때만)."""
    company, fins = DartAdapter().normalize(
        DartAdapter().fetch("00126380", "2024", "11011")
    )
    assert company["market"] == "KOSPI"
    assert company["stock_code"] == "005930"
    assert fins[0]["total_assets"] and fins[0]["total_assets"] > 0


# ── 일괄 코드리뷰(2026-07-13, GPT) 회귀 테스트 (1.9) ──

def test_dividend_total_skips_non_mapping_rows() -> None:
    """[High] malformed 행이 AttributeError로 재무 적재 전체를 죽이지 않음."""
    from app.ingest.dart import _dividend_total

    assert _dividend_total(["broken", None, 42]) is None
    assert _dividend_total(
        ["broken", {"se": "현금배당금총액(백만원)", "thstrm": "100"}]
    ) == 100_000_000  # 유효 행은 계속 처리


def test_dividend_total_conflicting_duplicates_is_null() -> None:
    """[Med] 동일 라벨 상충값 → 확정 금지(null). 동일값 중복은 확정."""
    from app.ingest.dart import _dividend_total

    rows = [
        {"se": "현금배당금총액(백만원)", "thstrm": "100"},
        {"se": "현금배당금총액(백만원)", "thstrm": "200"},
    ]
    assert _dividend_total(rows) is None
    same = [
        {"se": "현금배당금총액(백만원)", "thstrm": "100"},
        {"se": "현금배당금총액(백만원)", "thstrm": "100"},
    ]
    assert _dividend_total(same) == 100_000_000


def test_dividend_total_negative_among_candidates_is_null() -> None:
    """[Med] 음수 후보가 섞이면 오염 신호 → 전체 null."""
    from app.ingest.dart import _dividend_total

    rows = [
        {"se": "현금배당금총액(백만원)", "thstrm": "(500)"},
        {"se": "현금배당금총액(백만원)", "thstrm": "100"},
    ]
    assert _dividend_total(rows) is None


def test_buyback_retired_krw_reads_sce() -> None:
    """[2026-08-04 2차] 소각 '금액'은 CF가 아니라 SCE(자본변동표)에 있다.

    소각은 비현금 사건이라 CF에 없는 게 회계적으로 당연했다(백로그 원안의 여섯 번째
    반전). SCE는 같은 사건이 자본 구성요소별 여러 행에 ±X로 갈라져 온다(동원산업:
    자본금 -104.6억 / 기타자본 +104.6억 / 나머지 0) — 합산하면 상쇄돼 0이므로
    |금액| 최대값을 사건 크기로 읽는다.
    """
    from app.ingest.dart import _buyback_retired_krw

    dongwon = [
        {"sj_div": "SCE", "account_id": "ifrs-full_CancellationOfTreasuryShares",
         "account_nm": "자기주식 소각", "thstrm_amount": "-10,460,770,000"},
        {"sj_div": "SCE", "account_id": "ifrs-full_CancellationOfTreasuryShares",
         "account_nm": "자기주식 소각", "thstrm_amount": "0"},
        {"sj_div": "SCE", "account_id": "ifrs-full_CancellationOfTreasuryShares",
         "account_nm": "자기주식 소각", "thstrm_amount": "10,460,770,000"},
    ]
    assert _buyback_retired_krw(dongwon) == 10_460_770_000
    # 이름 변형 셋(실측 라벨 분포) — 태그 없이도 이름으로 잡힌다(현대백화점형)
    for name in ("자기주식 소각", "자기주식의 소각", "자기주식소각"):
        rows = [{"sj_div": "SCE", "account_id": "dart_TreasuryShareTransactions",
                 "account_nm": name, "thstrm_amount": "69,369,512,000"}]
        assert _buyback_retired_krw(rows) == 69_369_512_000, name


def test_buyback_retired_krw_rejects_mixed_rows() -> None:
    """혼합 행은 소각을 분해할 수 없다 — null이 정답(우리금융·콜마·현대모비스 실측).

    '순증감'·'변동'·'취득 및 처분'은 소각 아닌 사건이 섞인 총액이라, 잡으면
    과대/과소가 아니라 **다른 것**을 재는 값이 된다('금융부채' 총액형과 같은 계열).
    """
    from app.ingest.dart import _buyback_retired_krw

    for name in ("자기주식 순증감", "자기주식의 변동", "자기주식의 취득 및 처분"):
        assert _buyback_retired_krw(
            [{"sj_div": "SCE", "account_nm": name, "thstrm_amount": "1,000"}]
        ) is None, name
    # CF의 소각 '비용'(수수료)은 소각 금액이 아니다(신한 실측 0.8억)
    assert _buyback_retired_krw(
        [{"sj_div": "CF", "account_nm": "자기주식의 소각 비용", "thstrm_amount": "81,000,000"}]
    ) is None
    # SCE 밖(sj_div 명시)의 동명 행은 잡지 않는다
    assert _buyback_retired_krw(
        [{"sj_div": "CF", "account_nm": "자기주식의 소각", "thstrm_amount": "1,000"}]
    ) is None


def test_buyback_retired_krw_normalize_gate() -> None:
    """소각 수량 0 확정 + SCE 행 없음 → 0 / 수량>0 + 행 없음 → null(취득액과 동일 게이트)."""
    from app.ingest.dart import DartAdapter

    raw = {
        "company": {"corp_code": "00000001", "corp_name": "테스트"},
        "periods": [{
            "year": 2024, "quarter": 4, "fs_div": "CFS",
            "accounts": {"자산총계": 1000},
            "buyback_retired_krw": None,
            # 표가 왔고 수치 전무 → 수량 (0, 0) 확정
            "buyback_rows": [{"se": "합계", "change_qy_acqs": "-", "change_qy_incnr": "-"}],
            "dividend_rows": [],
        }],
    }
    _, recs = DartAdapter().normalize(raw)
    assert recs[0]["buyback_retired_amount"] == 0
    assert recs[0]["buyback_retired_krw"] == 0  # 수량 0 확정이 금액 0을 지지

    raw["periods"][0]["buyback_rows"] = [
        {"se": "합계", "change_qy_acqs": "1,000", "change_qy_incnr": "1,000"}
    ]
    _, recs = DartAdapter().normalize(raw)
    assert recs[0]["buyback_retired_amount"] == 1000
    assert recs[0]["buyback_retired_krw"] is None  # 소각은 했는데 액수를 모른다


def test_buyback_retired_krw_subsidiary_and_all_zero() -> None:
    """SK디스커버리 실측 회귀: ①종속회사 소각은 우리 주주환원이 아니다(취득액 규칙과
    동일) ②전부 0인 그룹은 None — 수량>0인데 0원 소각은 모순, 0으로 세탁 금지."""
    from app.ingest.dart import _buyback_retired_krw

    subsidiary = [{"sj_div": "SCE", "account_id": "ifrs-full_CancellationOfTreasuryShares",
                   "account_nm": "종속회사 자기주식소각", "thstrm_amount": "5,000"}]
    assert _buyback_retired_krw(subsidiary) is None
    all_zero = [{"sj_div": "SCE", "account_id": "ifrs-full_CancellationOfTreasuryShares",
                 "account_nm": "자기주식 소각", "thstrm_amount": "0"}] * 3
    assert _buyback_retired_krw(all_zero) is None
