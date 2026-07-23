"""Story 5-1 — 밸류업 공시 목표 파싱(주주환원율 신규 필드) 검증.

기존 파서 테스트는 test_valueup_ingest.py에 있다. 이 파일은 5-1에서 추가된
총주주환원율 목표 추출과 "과거 실적 오독 방지" 규칙만 다룬다.
"""
# ── 5-1: 주주환원율 목표(배당성향과 다른 지표) ──

def test_total_return_target_parsed_separately() -> None:
    """AC1: 주주환원율 목표는 target_total_return_ratio로, 배당성향과 섞이지 않는다."""
    from app.ingest.dart_valueup import parse_targets

    got = parse_targets("□ 주주환원 확대\n- 주주환원율 중장기 50% 목표\n- K-ICS 비율 유지")
    assert got["target_total_return_ratio"] == 50.0
    assert got["target_payout_ratio"] is None  # 배당성향 필드는 건드리지 않는다


def test_total_return_past_result_is_rejected() -> None:
    """실샘플 회귀: 이행 실적으로 등장한 주주환원율을 목표로 오독하지 않는다.

    계획 공시는 목표와 실적을 한 문서에 함께 싣는다 — 라벨+숫자만 보면 실데이터 13건 중
    5건이 과거 실적이었다(고려아연 268%, KT&G 108.9%, HMM 72.8% 등).
    """
    from app.ingest.dart_valueup import parse_targets

    for text in (
        "- '25년 6월 자사주 전량 소각 완료\n- '25년 총 주주환원율 268.0%\n- '25년 유보율 9,504%",
        "- 자기주식 취득 및 소각완료 : 2조 1,432억원\n- 총주주환원율 72.8%\n□ 지배구조",
        "③ 주주환원 현황('22~'24 3년 평균 주주환원율 78%)\n3. 계획",
    ):
        assert parse_targets(text)["target_total_return_ratio"] is None


def test_total_return_picks_target_over_nearby_result() -> None:
    """한 문서에 실적과 목표가 같이 있으면 **목표 쪽**을 집는다(실샘플 plan 33)."""
    from app.ingest.dart_valueup import parse_targets

    text = (
        "③ 주주환원 현황('22~'24 3년 평균 주주환원율 78%)\n"
        "3. 계획 및 목표\n"
        "③ 주주환원: '25~'27 3년 평균 주주환원율 40% 목표\n"
    )
    assert parse_targets(text)["target_total_return_ratio"] == 40.0


def test_total_return_does_not_steal_other_indicator_marker() -> None:
    """[교차리뷰 2026-07-23 CONFIRMED] 표지 창이 다른 지표의 목표 표지를 훔치지 않는다.

    _TARGET_MARK가 경쟁 라벨을 배제하기 전에는 "주주환원율 50% ROE 목표 12%"가 ROE의
    '목표'를 빌려 50을 총주주환원율 목표로 오채택했다(틀린 non-null → NFR2 위반). 값과 표지
    사이에 경쟁 지표 라벨(ROE·배당성향 등)이 끼면 순위 대상에서 뺀다(애매하면 null).
    """
    from app.ingest.dart_valueup import parse_targets

    for text in (
        "주주환원율 50% ROE 목표 12%",       # ROE의 목표를 빌림
        "총주주환원율 50% ROE 12% 목표",     # ROE 라벨을 건너 표지 도달
        "□ 주주환원율 45% 배당성향 30% 목표",  # 배당성향의 목표를 빌림
    ):
        assert parse_targets(text)["target_total_return_ratio"] is None

    # 대조군: 값과 표지 사이에 경쟁 라벨이 없으면 정상 채택(과잉 차단 아님)
    assert parse_targets("주주환원율 중장기 50% 목표")["target_total_return_ratio"] == 50.0
