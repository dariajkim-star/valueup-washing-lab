"""Story 1.5 — 밸류업 공시 어댑터 파싱·멱등 upsert 검증 (라이브 키 없이 fixture)."""

from __future__ import annotations

import io
import zipfile

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.ingest.dart import DartAdapterError
from app.ingest.dart_valueup import (
    DartDocumentError,
    DartValueupAdapter,
    _parse_date,
    _strip_tags,
    _zip_to_text,
    parse_targets,
)
from app.models import Base, Company, ValueupPlan
from app.repositories.valueup_plan import upsert_valueup_plan

# 가짜 공시 원문(자유서식 텍스트)
SAMPLE = (
    "당사는 기업가치 제고 계획을 다음과 같이 공시합니다. "
    "목표 ROE 10% 이상을 2024년 ~ 2026년 기간 동안 달성하고, "
    "배당성향 30%를 목표로 합니다. 목표 PBR 1.0배. "
    "주주가치 제고를 위해 자기주식 취득 및 소각을 계획합니다."
)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Company(corp_code="00000001", corp_name="테스트"))
        s.commit()
        yield s


def test_parse_targets_extracts_all() -> None:
    """AC2: raw_text에서 목표필드가 추출된다."""
    t = parse_targets(SAMPLE)
    assert t["target_roe"] == 10.0
    assert t["target_payout_ratio"] == 30.0
    assert t["target_pbr"] == 1.0
    assert t["period_start"] == "2024"
    assert t["period_end"] == "2026"
    assert t["buyback_planned"] is True


def test_parse_targets_missing_is_null() -> None:
    """AC3/NFR2: 목표 수치가 없으면 해당 필드 null, 수집 실패 없음."""
    t = parse_targets("기업가치 제고 계획 공시. 구체적 목표 수치는 추후 공시.")
    assert t["target_roe"] is None
    assert t["target_payout_ratio"] is None
    assert t["target_pbr"] is None
    assert t["period_start"] is None
    assert t["buyback_planned"] is None


def test_payout_only_matches_배당성향_not_주주환원율() -> None:
    """리뷰 E1: 주주환원율은 배당성향과 다른 지표 → target_payout_ratio에 넣지 않는다."""
    t = parse_targets("주주환원율 35%를 목표로 합니다.")  # 배당성향 언급 없음
    assert t["target_payout_ratio"] is None
    t2 = parse_targets("배당성향 25% 목표")
    assert t2["target_payout_ratio"] == 25.0


def test_zip_to_text_and_strip() -> None:
    """document.xml ZIP 해제 + 태그→개행(경계 보존). 비ZIP/빈은 DartDocumentError로 격리."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("doc.xml", "<DOCUMENT><P>목표 ROE 10%</P></DOCUMENT>".encode("utf-8"))
    text = _zip_to_text(buf.getvalue())
    assert "목표 ROE 10%" in text
    assert "<" not in text and ">" not in text
    # 비ZIP(오류 HTML/XML)·빈 응답은 '빈 원문'으로 오인하지 않고 예외로 격리
    with pytest.raises(DartDocumentError):
        _zip_to_text(b"not a zip")
    with pytest.raises(DartDocumentError):
        _zip_to_text(b"")
    # 태그 자리는 개행으로 → 셀/문단 경계 보존
    assert _strip_tags("<a>x</a><b>y</b>") == "x\ny"


def test_pbr_requires_bae_unit() -> None:
    """PBR은 '배' 단위 필수 — 연도·페이지번호를 PBR로 오탐하지 않음(G1)."""
    assert parse_targets("PBR 개선 2027년까지 추진")["target_pbr"] is None
    assert parse_targets("목표 PBR 1.5배")["target_pbr"] == 1.5
    assert parse_targets("PBR 200배")["target_pbr"] is None  # 비현실적 → 배제


def test_percent_point_not_absolute() -> None:
    """'%p'(퍼센트포인트 증감)를 절대목표로 오독하지 않음(G4)."""
    assert parse_targets("ROE 10%p 개선")["target_roe"] is None
    assert parse_targets("ROE 10% 이상")["target_roe"] == 10.0


def test_buyback_negation_and_past() -> None:
    """자사주 부정·과거 문맥은 False, 계획은 True, 미언급은 None(G5)."""
    assert parse_targets("자사주 취득 계획 없음")["buyback_planned"] is False
    assert parse_targets("자기주식 취득하지 않기로")["buyback_planned"] is False
    assert parse_targets("자사주 소각 계획")["buyback_planned"] is True
    assert parse_targets("배당 확대 예정")["buyback_planned"] is None


def test_period_order_validated() -> None:
    """목표기간 start<=end만 인정(역순 범위는 오탐이므로 null)(G6)."""
    assert parse_targets("2024~2026년")["period_start"] == "2024"
    t = parse_targets("2026~2024")
    assert t["period_start"] is None and t["period_end"] is None


def test_strip_tags_prevents_cross_cell_grab() -> None:
    """표 셀 경계(개행)를 넘어 인접 지표 %를 잡지 않는다(G2)."""
    doc = "<TABLE><TR><TD>ROE 개선</TD><TD>배당성향 30%</TD></TR></TABLE>"
    t = parse_targets(_strip_tags(doc))
    assert t["target_roe"] is None           # ROE 셀엔 %가 없음(개행 못 넘음)
    assert t["target_payout_ratio"] == 30.0   # 배당성향 셀에서만


def test_parse_date_strict() -> None:
    """날짜 엄격검증: 무효는 None(적재 제외)(G10)."""
    assert _parse_date("20240315") == "2024-03-15"
    assert _parse_date("20241399") is None  # 13월 99일
    assert _parse_date("2024") is None
    assert _parse_date("") is None
    assert _parse_date(None) is None


def test_upsert_full_replace_clears_stale(session: Session) -> None:
    """G9: 재파싱 null이 과거 오탐 non-null을 정정한다(유효 문서 기반 전체 교체)."""
    upsert_valueup_plan(session, {
        "corp_code": "00000001", "disclosure_date": "2024-03-15",
        "target_pbr": 2027.0, "raw_text": "old"})  # 최초 오탐 저장
    session.commit()
    upsert_valueup_plan(session, {
        "corp_code": "00000001", "disclosure_date": "2024-03-15",
        "target_pbr": None, "raw_text": "new"})  # 고쳐진 파서: null
    session.commit()
    obj = session.scalars(select(ValueupPlan)).one()
    assert obj.target_pbr is None  # 옛 오값 정정됨
    assert obj.raw_text == "new"


def test_fetch_isolates_document_failure(monkeypatch) -> None:
    """G7: 한 문서 실패가 그 종목의 다른 공시를 날리지 않는다(부분 보존)."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "dart_api_key", SecretStr("k"))
    adapter = DartValueupAdapter()
    listing = {"status": "000", "total_page": 1, "list": [
        {"report_nm": "기업가치 제고 계획", "rcept_no": "A", "rcept_dt": "20240301"},
        {"report_nm": "기업가치 제고 계획", "rcept_no": "B", "rcept_dt": "20240401"},
    ]}
    monkeypatch.setattr(adapter, "_get_json", lambda *a, **k: listing)

    def fake_doc(key, rcept_no):
        if rcept_no == "A":
            return "배당성향 20% 목표"
        raise DartDocumentError("boom")
    monkeypatch.setattr(adapter, "_fetch_document", fake_doc)

    raw = adapter.fetch("00000001", "20240101", "20241231")
    assert [p["disclosure_date"] for p in raw["plans"]] == ["2024-03-01"]  # A만 성공
    assert any(f[0] == "B" for f in raw["failed"])  # B는 격리 실패


def test_fetch_skips_invalid_date(monkeypatch) -> None:
    """무효 rcept_dt 공시는 자연키 붕괴 방지 위해 적재 제외(G10)."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "dart_api_key", SecretStr("k"))
    adapter = DartValueupAdapter()
    listing = {"status": "000", "total_page": 1, "list": [
        {"report_nm": "기업가치 제고 계획", "rcept_no": "X", "rcept_dt": "20241399"},
    ]}
    monkeypatch.setattr(adapter, "_get_json", lambda *a, **k: listing)
    raw = adapter.fetch("00000001", "20240101", "20241231")
    assert raw["plans"] == []
    assert any(f[0] == "X" for f in raw["failed"])


def test_normalize_preserves_raw_text() -> None:
    """AC2/AC3: normalize가 목표필드 + raw_text 원문을 레코드로 만든다."""
    raw = {
        "corp_code": "00000001",
        "plans": [
            {"disclosure_date": "2024-03-15", "report_nm": "기업가치 제고 계획",
             "raw_text": SAMPLE},
        ],
    }
    recs = DartValueupAdapter().normalize(raw)
    assert len(recs) == 1
    rec = recs[0]
    assert rec["corp_code"] == "00000001"
    assert rec["disclosure_date"] == "2024-03-15"
    assert rec["target_roe"] == 10.0
    assert rec["raw_text"] == SAMPLE  # 원문 보존


def test_upsert_idempotent_and_updates(session: Session) -> None:
    """AC4: (corp_code, disclosure_date) 자연키 멱등 — 재실행 중복 없음, 값 갱신."""
    adapter = DartValueupAdapter()
    raw = {
        "corp_code": "00000001",
        "plans": [
            {"disclosure_date": "2024-03-15", "raw_text": SAMPLE},
        ],
    }
    recs = adapter.normalize(raw)
    adapter.upsert(session, recs)
    session.commit()
    adapter.upsert(session, recs)  # 재실행
    session.commit()
    assert session.scalar(select(func.count()).select_from(ValueupPlan)) == 1

    recs[0]["target_roe"] = 12.5  # 값 변경 후 재적재
    adapter.upsert(session, recs)
    session.commit()
    obj = session.scalars(select(ValueupPlan)).one()
    assert obj.target_roe == 12.5
    assert obj.raw_text == SAMPLE


def test_multiple_disclosures_multiple_rows(session: Session) -> None:
    """리뷰 E2: 한 종목이 여러 공시(예고·본공시) → 날짜별 행."""
    adapter = DartValueupAdapter()
    raw = {
        "corp_code": "00000001",
        "plans": [
            {"disclosure_date": "2024-03-15", "raw_text": "배당성향 20% 목표"},
            {"disclosure_date": "2024-09-20", "raw_text": "배당성향 30% 목표"},
        ],
    }
    adapter.upsert(session, adapter.normalize(raw))
    session.commit()
    assert session.scalar(select(func.count()).select_from(ValueupPlan)) == 2


def test_fetch_without_key_raises(monkeypatch) -> None:
    """AC5: DART_API_KEY 미설정 시 명확한 에러(키/URL 미노출)."""
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "dart_api_key", SecretStr(""))
    with pytest.raises(DartAdapterError, match="DART_API_KEY"):
        DartValueupAdapter().fetch("00000001", "20240101", "20241231")


# ── Story 1.10: 실샘플(리허설 79건) 기반 파서 튜닝 ──

def test_roe_gap_allows_parenthesized_qualifier() -> None:
    """실샘플: `ROE 목표(`24~`30년 평균) : 15%+ α` — 괄호 안 숫자 때문에 기존 gap 규칙 실패."""
    t = parse_targets("ROE 목표(`24~`30년 평균) : 15%+ α")
    assert t["target_roe"] == 15.0


def test_roe_alias_자기자본이익률() -> None:
    """실샘플 6건: 'ROE' 대신 '자기자본이익률' 표기."""
    assert parse_targets("자기자본이익률 12% 달성")["target_roe"] == 12.0


def test_arrow_takes_target_side_not_current() -> None:
    """1.5 defer F3/G2: '현재 → 목표'에서 우변(목표)을 채택. 실샘플: 1.8% → ... 8.3%."""
    t = parse_targets("ROE : 2024년말 1.8% → 2025년말 8.3%")
    assert t["target_roe"] == 8.3
    t2 = parse_targets("배당성향 20% → 30% 확대")
    assert t2["target_payout_ratio"] == 30.0


def test_arrow_absent_keeps_first_match() -> None:
    """화살표 없으면 기존 동작(첫 매칭) 유지 — 회귀 방지."""
    assert parse_targets("ROE 10% 이상")["target_roe"] == 10.0


def test_period_backtick_two_digit_years() -> None:
    """실샘플: `24~`30년 (백틱/따옴표 2자리 연도) → 2024~2030 확장."""
    t = parse_targets("ROE 목표(`24~`30년 평균) : 15%")
    assert t["period_start"] == "2024"
    assert t["period_end"] == "2030"
    t2 = parse_targets("'25~'27년 주주환원 계획")
    assert t2["period_start"] == "2025"
    assert t2["period_end"] == "2027"


# ── Story 1.11: 축=0 구간 전수 재판독 (v2-backlog P1-2 2차) ──
#
# 배경: P1-2 1차의 결론("본문에 정말 목표가 없다")은 `no_targets` 175건만 보고 내린
# 것이었다. 축=0 구간 210건 중 나머지 35건(refiling 19 + other_metric 16)은 전수
# 판독된 적이 없었고, 거기서 5건이 나왔다. 아래는 **실샘플 원문 그대로**다 —
# 정규화한 문자열로 쓰면 개행 버그가 테스트를 통과한다(1.11 Dev Notes).


def test_roe_label_and_value_on_separate_lines() -> None:
    """원인 A · 서울보증보험(plan 98·99): 라벨과 값이 다른 줄.

    `_plain_gap`이 개행을 금지해 끊겼다. 공시가 `③ ROE` 다음 줄에 `- 중장기 목표 10%`를
    쓰는 불릿 서식이라 통째로 버려지고 있었다.
    """
    text = (
        "① 주주환원 \n- 업계 최고 수준의 총주주환원 \n② K-ICS 비율 \n"
        "- 중장기 목표 320% 이상 \n③ ROE \n- 중장기 목표 10% \n"
        "2. 기업가치 제고를 위한 실행방안"
    )
    assert parse_targets(text)["target_roe"] == 10.0


def test_newline_requires_target_marker_on_next_line() -> None:
    """원인 A의 안전장치: 개행을 넘으려면 **다음 줄이 목표를 말해야** 한다.

    개행 너머는 대개 다른 항목이다. 표지 없이 열면 라벨이 무관한 줄의 숫자를 훔친다.
    """
    assert parse_targets("③ ROE \n2. 기업가치 제고를 위한 실행방안 50%")["target_roe"] is None


def test_newline_does_not_cross_into_competing_metric() -> None:
    """원인 A의 안전장치 2: 개행을 열어도 경쟁 지표의 숫자는 훔치지 않는다.

    G2(표 셀 경계) 가드와 같은 계열 — 1.10 일괄리뷰 High 3건이 전부 이 방향이었다.
    """
    assert parse_targets("ROE 개선 \n- 배당성향 목표 30%")["target_roe"] is None


def test_return_target_marker_before_the_value() -> None:
    """원인 B · 코웨이(plan 317): 목표 표지가 값 **앞**에 있다.

    `_TARGET_MARK`는 값 뒤 12자만 본다. 여기서 표지(`상향`)는 라벨과 값 사이에 있고,
    값 뒤에는 다음 항목이 온다.
    """
    text = "2) 주주환원율 상향: 당기순이익(연결)의 40% \n3) 재무건전성과 자본효율성을 고려한 적정 자본구조"
    assert parse_targets(text)["target_total_return_ratio"] == 40.0


def test_return_range_with_marker_on_following_line() -> None:
    """원인 C · 한솔케미칼(plan 215): 표지가 값 뒤 15자째(창은 12자) + 개행 너머.

    OQ-1 확정대로 범위는 **하한**을 채택하고 원문 범위를 보존한다.
    """
    text = "2) 주주환원 확대 \n- 주주환원율 20~50% \n- 2026년 주주환원 확대 적극 검토"
    t = parse_targets(text)
    assert t["target_total_return_ratio"] == 20.0
    assert "total_return_ratio:20~50" in (t["target_ranges"] or "")


def test_return_past_performance_is_not_taken_as_target() -> None:
    """원인 C의 안전장치 · 한솔 실측 함정: **같은 문서에 목표와 실적이 나란히 있다**.

    `2) 주주환원 초과 달성 - 주주환원율 57%`는 2025년 **이행 실적**이다.
    표지 조건을 느슨하게 풀면 57%를 목표로 삼는다 — `_TARGET_MARK`가 존재하는 이유다
    (5-1 실샘플: 라벨+숫자만 보면 13건 중 5건이 과거 실적이었다).
    """
    text = (
        "1. 2026년 기업가치 제고 계획 \n1) 지속적인 성장 \n"
        "- 연결 매출액, 영업이익 연 10% 성장 \n2) 주주환원 확대 \n"
        "- 주주환원율 20~50% \n- 2026년 주주환원 확대 적극 검토 \n3) 투자자 소통 강화 \n"
        "2. 2025년 기업가치 제고 계획 이행 현황 \n1) 성장 목표 달성 \n"
        "- 매출액 14%, 영업이익 21% 성장 \n2) 주주환원 초과 달성 \n- 주주환원율 57%"
    )
    assert parse_targets(text)["target_total_return_ratio"] == 20.0


def test_return_bare_performance_still_rejected() -> None:
    """회귀 방어(5-1): 표지 없는 주주환원율 실적은 여전히 채택하지 않는다."""
    assert parse_targets("'25년 총 주주환원율 268.0%")["target_total_return_ratio"] is None
    assert parse_targets("3년 평균 주주환원율 78%(현황)")["target_total_return_ratio"] is None


def test_separate_basis_return_ratio_is_not_adopted() -> None:
    """원인 D · 현대지에프홀딩스(plan 72): **역순 + 회사 자기 정의**.

    `별도 당기순이익 기준 80% 이상 주주환원율 지향` — 값이 라벨 앞에 오는 역순이고,
    분모가 **별도** 당기순이익이다. 우리 실적은 연결 기준이라 이 값을 채택하면
    **다른 정의로 채점**하게 된다.

    2026-08-05에 환원율 축 소각 기준 재론을 기각한 근거가 정확히 이것이었다 —
    *"기업마다 총주주환원율 정의가 다르다"*. 그때 죽인 것을 여기서 되살리지 않는다.
    이 건은 조건부 백로그 **P1-9의 트리거 후보 1건**으로만 계상한다.

    → 그래서 역순 정규식을 **추가하지 않는다**. 실증된 유일한 역순 샘플이 '채택하면
      안 되는 건'이므로, 규칙을 넓히는 것은 관념적 개선이 된다(1.10 Debug Log 규율).
    """
    text = (
        "3. 주주환원 확대 \n- '25년 부 100억 이상 반기 배당 실시 \n"
        "- '27년 배당금총액 500억(결산+반기) 수준 지향 \n"
        "- '25년 부 시가배당률 5% 수준 지향 \n"
        "- 별도 당기순이익 기준 80% 이상 주주환원율 지향 \n4. 소통 강화"
    )
    assert parse_targets(text)["target_total_return_ratio"] is None


def test_lguplus_two_ranges_both_preserved() -> None:
    """plan 350 LG유플러스 — **T0 스캔 밖에서 바뀐 유일한 건**(축=2 구간).

    한 문서에 범위가 둘(`ROE 8~10%`·`주주환원율 40~60%`)이고, OQ-1은 하한 채택과
    **원문 범위 보존을 함께** 요구한다. 실 DB에는 `total_return_ratio:40~60`이 빠져
    있었다(백필이 기존 `target_ranges`를 덮지 않는 결함) — 파싱 층에서 둘 다 나오는지를
    여기서 고정해, 다음에 어긋나면 그것이 백필 문제임이 바로 드러나게 한다.
    """
    text = (
        "[추진 목표(I)] 중장기 ROE 8~10% \n- 실행계획 \n"
        "① (B2B) AIDC를 통한 성장동력 강화 \n② (B2C) 디지털 기반 유통구조 전환 \n"
        "③ (운영) AX 추진 및 사업구조 개선 \n[추진 목표(II)] 주주환원율 40~60% \n"
        "- 실행계획 \n① 중장기 적정 자본구조를 부채비율 100%로 설정"
    )
    t = parse_targets(text)
    assert t["target_roe"] == 8.0
    assert t["target_total_return_ratio"] == 40.0
    ranges = t["target_ranges"] or ""
    assert "roe:8~10" in ranges
    assert "total_return_ratio:40~60" in ranges


# ── code-review 2026-08-07 회귀 테스트 ──
#
# 3계층 리뷰(Blind / Edge Case / Acceptance)가 재현한 오탐 경로. 전부 **현 코퍼스에서는
# 발현 0건**이었지만, 1.11이 개행을 열면서 구조적으로 열린 문이었다. 진단이 하나로 모였다:
# **1.10의 오탐 방어는 전부 *같은 줄* 안의 경쟁 라벨 배제였고, 개행 금지가 그 목록(5개)의
# 불완전함을 덮고 있었다.**


def test_newline_does_not_cross_into_unlisted_metric_label() -> None:
    """[AC 4] 경쟁 라벨 **목록**이 아니라 라벨의 **꼴**로 막는다.

    `_OTHERS_FOR_ROE`는 5개(배당성향·주주환원·PBR·영업이익·부채비율)뿐이라, 목록 밖
    지표가 다음 줄에 오면 그대로 통과했다. **K-ICS는 이 스토리의 실샘플 plan 98의 인접
    항목이다** — 원문에서 ROE가 뒤에 왔기 때문에 살았을 뿐, 방어가 아니라 배치 운이었다.
    """
    assert parse_targets("ROE 개선 \n- K-ICS 비율 목표 320%")["target_roe"] is None
    assert parse_targets("③ ROE \n- 배당수익률 목표 3%")["target_roe"] is None
    assert parse_targets("③ ROE \n- 매출총이익률 목표 25%")["target_roe"] is None
    assert parse_targets("② ROE \n- 자사주 소각률 목표 50%")["target_roe"] is None


def test_newline_requires_bullet_and_exactly_one_break() -> None:
    """주석이 약속한 방어가 코드에 **없었다** — `_BULLET`이 옵셔널이고 `\\s`가 개행을 먹었다."""
    assert parse_targets("ROE 개선 \n중장기 목표 12%")["target_roe"] is None  # 불릿 없음
    assert parse_targets("ROE \n \n \n 목표 10%")["target_roe"] is None  # 빈 줄 여러 개
    assert parse_targets("③ ROE \n① \n\n 목표 10%")["target_roe"] is None  # 개행 3회


def test_premark_rejects_performance_wording() -> None:
    """값 **앞** 표지가 유일한 앵커인 tier — 그 표지가 실적 서술에도 쓰이면 안 된다.

    `_premark_gap`에는 값 뒤 가드(`_TARGET_MARK`)가 없다. 커밋 메시지는 그 방어선을
    유지했다고 적었지만 이 tier는 그 앞을 지나가지 않는다. 그래서 표지를 목표어로 좁히고
    (`확대`·`수준`·`이상` 제거), 표지와 값 사이에 실적어가 끼면 끊는다.
    """
    for text in (
        "주주환원율 확대 노력으로 57%를 달성",
        "주주환원율은 업계 최고 수준인 57%를 기록하였습니다",
        "주주환원율 이행계획에 따라 배당한 결과 57%",
        "총주주환원율 실적: 예상 수준을 넘어선 268.0%",
        "주주환원율 상향 이전 실적인 32%",
    ):
        assert parse_targets(text)["target_total_return_ratio"] is None, text
    # 실증 샘플(코웨이 317)은 계속 통과해야 한다 — 좁히되 죽이지 않는다.
    coway = "2) 주주환원율 상향: 당기순이익(연결)의 40% \n3) 재무건전성과 자본효율성"
    assert parse_targets(coway)["target_total_return_ratio"] == 40.0


def test_newline_mark_excludes_performance_word() -> None:
    """`_NEWLINE_MARK`에 `달성`이 있었다 — `_TARGET_MARK`가 **의도적으로 뺀** 단어다.

    한솔(215) 원문의 실적 줄이 정확히 `2) 주주환원 초과 달성 \\n- 주주환원율 57%`이고,
    라벨과 `달성`의 **순서만** 반대여서 통과하지 못했을 뿐이다.
    """
    assert parse_targets("주주환원율 \n- 초과 달성 57%")["target_total_return_ratio"] is None
    assert parse_targets("ROE \n- 초과 달성 12%")["target_roe"] is None


def test_wide_window_does_not_borrow_marker_across_sentence() -> None:
    """넓힌 창만 `[^\\n]`이라 다음 줄 **남의 문장**에서 표지를 빌려왔다."""
    text = "주주환원율 20~50% 검토 \n2028년까지 매출 5조원 달성"
    assert parse_targets(text)["target_total_return_ratio"] is None


def test_range_tier_precedes_premark_in_fallback_order() -> None:
    """폴백 순서는 **증거가 강한 것부터**.

    범위(`30~50%`)는 형태적 증거를 갖지만 premark의 앵커는 낱말 하나다. 느슨한 쪽이
    먼저 돌면 강한 증거를 선점한다 — 실제로 그 순서였고, 자사주 소각 비율 `2%`가
    환원율 목표로 채택될 수 있었다.
    """
    text = (
        "주주환원율 상향 계획에 따라 자사주 2% 소각을 검토하며, \n"
        "- 중장기 주주환원율 30~50% 목표"
    )
    t = parse_targets(text)
    assert t["target_total_return_ratio"] == 30.0
    assert "total_return_ratio:30~50" in (t["target_ranges"] or "")


def test_period_two_digit_requires_marker() -> None:
    """2자리 연도는 백틱/따옴표 표식 필수 — '24~26개월' 같은 비연도 오탐 방지."""
    t = parse_targets("향후 24~26개월 내 실행")
    assert t["period_start"] is None


def test_report_nm_negative_filter() -> None:
    """1.5 defer F9: 이행현황·철회는 계획 아님 → 제외. 정정공시는 유지."""
    from app.ingest.dart_valueup import _is_plan_report

    assert _is_plan_report("기업가치 제고 계획") is True
    assert _is_plan_report("[기재정정]기업가치 제고 계획") is True
    assert _is_plan_report("기업가치 제고 계획 이행현황") is False
    assert _is_plan_report("기업가치 제고 계획 철회신고서") is False
    assert _is_plan_report("주요사항보고서") is False


# ── 일괄 코드리뷰(2026-07-13, GPT) 회귀 테스트 ──

def test_label_gap_rejects_competing_metric_in_paren() -> None:
    """[High] 괄호 안 %·경쟁 지표가 ROE 값을 훔치던 오탐(GPT 재현 그대로)."""
    assert parse_targets("ROE(2024년 5%) 배당성향 30%")["target_roe"] is None
    assert parse_targets("ROE 목표(PBR 0.8배, 배당성향 25%) : 15%")["target_roe"] is None
    # 실샘플 정상 케이스는 계속 통과(괄호 안 숫자·백틱 허용)
    assert parse_targets("ROE 목표(`24~`30년 평균) : 15%")["target_roe"] == 15.0


def test_label_gap_rejects_competing_metric_in_plain_gap() -> None:
    """[High] 라벨-값 사이에 경쟁 지표가 오면 매칭 중단."""
    assert parse_targets("ROE 미제시 배당성향 30%")["target_roe"] is None
    assert parse_targets("배당성향 미제시 ROE 10%")["target_payout_ratio"] is None


def test_arrow_rejects_competing_metric_between() -> None:
    """[High] 다른 지표의 화살표를 ROE 목표로 훔치던 오탐(GPT 재현 그대로)."""
    t = parse_targets("ROE 목표 미제시, 배당성향 20% → 30%")
    assert t["target_roe"] is None
    assert t["target_payout_ratio"] == 30.0
    assert parse_targets("ROE는 별도 목표 없음 / 영업이익률 5% → 10%")["target_roe"] is None


def test_arrow_does_not_override_earlier_plain_target() -> None:
    """[Med] 앞의 명시 목표가 뒤의 과거실적 화살표에 밀리지 않음(위치 우선)."""
    text = "ROE 목표 12% 달성 계획.\n과거 추이: ROE 5% → 8%"
    assert parse_targets(text)["target_roe"] == 12.0


def test_period_prefers_keyword_anchored_range() -> None:
    """[Med] 과거 비교기간이 아니라 '계획' 인접 범위 선택(GPT 재현 그대로)."""
    t = parse_targets("비교기간 2020~2022, 기업가치 제고 계획 2025~2030")
    assert t["period_start"] == "2025"
    assert t["period_end"] == "2030"


def test_period_multiple_unanchored_is_null() -> None:
    """[Med] 앵커 없는 상이한 범위 다수 → 애매 → null(NFR2)."""
    t = parse_targets("2019~2021 실적. 2022~2024 추이.")
    assert t["period_start"] is None


def test_period_single_candidate_still_works() -> None:
    """회귀: 단일 후보는 앵커 없어도 채택(기존 동작 유지)."""
    assert parse_targets("2024~2026년")["period_start"] == "2024"


def test_get_json_non_dict_wrapped(monkeypatch) -> None:
    """[High] 비-dict JSON(list/str)이 AttributeError로 누출되지 않고 DartAdapterError."""
    from app.ingest.dart_valueup import DartValueupAdapter

    adapter = DartValueupAdapter()

    class _Resp:
        def raise_for_status(self) -> None: pass
        def json(self): return ["not", "a", "dict"]

    monkeypatch.setattr(adapter._session, "get", lambda *a, **k: _Resp())
    with pytest.raises(DartAdapterError):
        adapter._get_json("list.json", {"crtfc_key": "K"})


def test_zip_total_size_cap() -> None:
    """[Med] 멤버별 한도만으론 부족 — 누적 압축해제 상한."""
    import io as _io
    import zipfile as _zf

    from app.ingest.dart_valueup import DartDocumentError, _zip_to_text

    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w", _zf.ZIP_DEFLATED) as z:
        member = ("가" * 1_000_000)  # ~3MB utf-8 × 20 = 총 한도 초과
        for i in range(20):
            z.writestr(f"doc{i}.xml", member)
    with pytest.raises(DartDocumentError, match="누적"):
        _zip_to_text(buf.getvalue())


# ── code-review 2026-08-07 ⑪⑫: target_ranges 축 단위 병합 ──


def test_backfill_merges_ranges_per_axis() -> None:
    """`target_ranges`는 한 칸에 여러 축이 들어가는 문자열이다.

    이전 가드(`not plan.target_ranges`)는 **축 하나라도 있으면 통째로 건너뛰었다.**
    plan 350(LG유플러스)이 `roe:8~10`을 갖고 있어 1.11이 회수한
    `total_return_ratio:40~60`이 유실됐고, 화면이 이 칸을 읽으므로 40~60% 약속이
    40% 단일 목표로 보였다(OQ-1의 '원문 범위 보존' 위반).
    """
    from app.analysis.backfill_targets import _merge_ranges

    merged, added, clashed = _merge_ranges("roe:8~10", "roe:8~10,total_return_ratio:40~60")
    assert merged == "roe:8~10,total_return_ratio:40~60"
    assert added == ["total_return_ratio"]
    assert clashed == []


def test_backfill_does_not_overwrite_existing_range() -> None:
    """기존 축은 덮지 않고 **보고**한다 — 스칼라 필드와 같은 정책.

    기존 값이 어떤 규칙에서 나왔는지 이 층에서 알 수 없다는 것이 그 정책의 이유다.
    """
    from app.analysis.backfill_targets import _merge_ranges

    merged, added, clashed = _merge_ranges("roe:8~10", "roe:9~11")
    assert merged == "roe:8~10"
    assert added == []
    assert clashed == [("roe", "8~10", "9~11")]


def test_backfill_range_merge_handles_empty_sides() -> None:
    """한쪽이 비어도 안전하다 — 파싱이 범위를 못 내면 기존 값을 그대로 둔다."""
    from app.analysis.backfill_targets import _merge_ranges

    assert _merge_ranges(None, "roe:8~10")[0] == "roe:8~10"
    assert _merge_ranges("roe:8~10", None)[0] == "roe:8~10"
    assert _merge_ranges(None, None)[0] == ""
