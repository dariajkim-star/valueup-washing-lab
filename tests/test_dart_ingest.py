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
