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
    """AC2/AC3: 미공시([])·미상(None)·파싱불가('-')·음수(도메인 밖) 전부 null."""
    from app.ingest.dart import _dividend_total

    assert _dividend_total([]) is None
    assert _dividend_total(None) is None
    assert _dividend_total([{"se": "현금배당금총액(백만원)", "thstrm": "-"}]) is None
    assert _dividend_total([{"se": "현금배당금총액(백만원)", "thstrm": "(500)"}]) is None


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


def test_buyback_totals_dash_is_none_per_field() -> None:
    """AC4: '-'/빈값(파싱불가)만 있는 필드는 None(unknown). 취득만 있고 소각은 '-'."""
    from app.ingest.dart import _buyback_totals

    rows = [{"acqs_mth1": "직접 취득", "acqs_mth2": "-", "acqs_mth3": "-",
             "change_qy_acqs": "3,000,000", "change_qy_incnr": "-"}]
    assert _buyback_totals(rows) == (3_000_000, None)


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
