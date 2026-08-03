"""P1-8 — 계획 기간 파싱. 확장분과 함께 **넓히지 않기로 한 것**도 고정한다.

실측 근거(2026-07-31, 목표는 읽었으나 기간 실패 212건에서 표현을 센 결과):
    중장기(수치없음) 71 · YYYY년까지 24 · 지속/매년 20 · 'YY년까지 15 ·
    N개년 13 · 향후 N년 12 · 표현 자체가 없음 94

넓히는 것은 **수치가 텍스트에 있는 것뿐**이다. "중장기"·"지속적으로"는 억지 추정하지 않고
미상으로 남긴다(SM-C1) — 커버리지보다 정확도 우선(NFR2).
"""

from __future__ import annotations

import pytest

from app.ingest.dart_valueup import parse_targets


def period(text: str, disclosure_date: str | None = "2026-03-20"):
    got = parse_targets(text, disclosure_date)
    return got["period_start"], got["period_end"]


class TestExistingRangeForms:
    """기존 계약(범위 표기) — 확장이 이걸 건드리지 않았음을 고정."""

    def test_year_range(self):
        assert period("계획 기간 2025~2027년 ROE 10%") == ("2025", "2027")

    def test_two_digit_range_with_mark(self):
        assert period("목표 `24~`30년 총주주환원율 50%") == ("2024", "2030")

    def test_conflicting_ranges_without_anchor_is_none(self):
        """앵커 없이 상이한 범위가 여럿이면 애매 → null(기존 규칙)."""
        assert period("2015~2018 실적 참고. 별첨 2020~2023 비교") == (None, None)


class TestEndOnlyForms:
    """[P1-8] 종료만 밝힌 공시 — 시작을 **공시일**로 본다(리드 결정 A).

    없는 값을 지어내는 것이 아니라 공시 행위가 약속의 시작점을 정의한다.
    2026-03-20에 "2030년까지 하겠다"고 밝혔다면 그 약속 구간은 공시일~2030이다.
    """

    def test_until_year(self):
        assert period("주주환원 지속 - 2030년까지 배당성향 30% 달성") == ("2026", "2030")

    def test_until_two_digit_year(self):
        assert period("목표: '28년까지 ROE 12% 달성") == ("2026", "2028")

    def test_wide_context_window(self):
        """서술이 길게 앞에 붙어도 잡는다 — 창 20으로는 14건을 놓쳤다."""
        text = "□ 주주환원 지속 - 안정적 재무건전성을 바탕으로 2030년까지 배당성향 30%"
        assert period(text) == ("2026", "2030")

    def test_conflicting_end_years_is_none(self):
        """종료연도가 상충하면 애매 → null(범위 표기와 같은 보수성)."""
        assert period("목표 ROE 10% 이상 유지(2027년까지) PBR 1.0배 달성(2030년까지)") == (None, None)

    def test_past_year_is_not_a_plan_period(self):
        """공시연도 이전 연도는 계획 기간이 아니다(과거 실적·비교 문맥)."""
        assert period("목표 대비 2023년까지의 실적은 다음과 같습니다") == (None, None)

    def test_no_disclosure_date_disables_inference(self):
        """기준점이 없으면 추정하지 않는다."""
        assert period("목표: 2030년까지 배당성향 30%", None) == (None, None)


class TestRelativeAndFromTo:
    def test_forward_n_years(self):
        """'향후 3개년' = 공시연도부터 3년(종료는 시작+2)."""
        assert period("향후 3개년 지향점을 제시할 예정입니다") == ("2026", "2028")

    def test_from_to_fiscal_years(self):
        """'23회계연도부터 '25회계연도까지 — 시작·종료가 둘 다 텍스트에 있다."""
        assert period("'23회계연도부터 '25회계연도까지 3개년 총주주환원율") == ("2023", "2025")

    def test_explicit_range_wins_over_end_only(self):
        """범위가 명시돼 있으면 그쪽이 우선 — 더 강한 근거다."""
        assert period("계획 2024~2026년. 2030년까지 지속 추진") == ("2024", "2026")


class TestNotWidened:
    """넓히지 **않기로** 한 것들 — 수치가 없으면 미상으로 남긴다."""

    @pytest.mark.parametrize("text", [
        "중장기적으로 핵심지표를 최대화하겠습니다",
        "중장기 목표 220% 이상",           # 값은 있지만 **기간**은 없다
        "지속적으로 주주환원을 확대하겠습니다",
        "매년 목표의 적정성을 분석할 예정입니다",
    ])
    def test_unquantifiable_expressions_stay_null(self, text):
        assert period(text) == (None, None)

    def test_absurd_span_rejected(self):
        """상한(20년)을 넘는 범위는 계획 기간이 아니라 오탐으로 본다."""
        assert period("목표 2000년부터 2060년까지") == (None, None)
