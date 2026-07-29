"""공시 선택 정책 — 최신 우선 + 0축이면 과거 폴백 (2026-07-29 리드 결정).

순수 함수라 DB 없이 검증한다. 이 규칙은 gap·opacity 두 엔진과 서빙이 공유하므로
여기서 깨지면 세 곳이 동시에 틀린다.
"""

from __future__ import annotations

from app.analysis.plan_selection import (
    NO_TARGETS,
    REFILING,
    choose_plan,
    disclosed_axis_count,
    opacity_axes,
)


def plan(**kw):
    base = {
        "plan_id": kw.pop("plan_id", 1),
        "disclosure_date": kw.pop("disclosure_date", "2024-01-01"),
        "target_roe": None,
        "target_payout_ratio": None,
        "target_total_return_ratio": None,
        "period_start": None,
        "buyback_planned": None,
        "body_signal": kw.pop("body_signal", NO_TARGETS),
        "body_reference_date": kw.pop("body_reference_date", None),
    }
    base.update(kw)
    return base


class TestAxisCounting:
    def test_empty_plan_has_zero_axes(self):
        assert disclosed_axis_count(plan()) == 0

    def test_payout_and_total_return_are_one_axis(self):
        """대체재 — 하나만 약속해도 '환원을 공시'한 것(둘 다 세면 이중 가중)."""
        assert disclosed_axis_count(plan(target_payout_ratio=30.0)) == 1
        assert disclosed_axis_count(plan(target_total_return_ratio=50.0)) == 1
        both = plan(target_payout_ratio=30.0, target_total_return_ratio=50.0)
        assert disclosed_axis_count(both) == 1  # 여전히 1축

    def test_buyback_false_counts_as_disclosed(self):
        """False = '자사주 계획 없음'을 **공시한** 것이라 미공시가 아니다."""
        assert opacity_axes(plan(buyback_planned=False))["buyback"] is False
        assert disclosed_axis_count(plan(buyback_planned=False)) == 1

    def test_all_four_axes(self):
        full = plan(target_roe=10.0, target_payout_ratio=30.0,
                    period_start="2025", buyback_planned=True)
        assert disclosed_axis_count(full) == 4


class TestChoosePlan:
    def test_none_when_no_candidates(self):
        assert choose_plan([]) is None

    def test_uses_latest_when_it_has_targets(self):
        latest = plan(plan_id=2, disclosure_date="2026-03-31", target_roe=12.0)
        older = plan(plan_id=1, disclosure_date="2024-10-29", target_roe=10.0)
        c = choose_plan([latest, older])
        assert c.plan["plan_id"] == 2
        assert c.used_fallback is False

    def test_falls_back_when_latest_is_a_cover_notice(self):
        """하나금융 실측 형태: 최신 0축, 과거 2축 → 과거를 쓰고 폴백으로 표시."""
        latest = plan(plan_id=3, disclosure_date="2026-03-31")  # 표지 통지문
        older = plan(plan_id=2, disclosure_date="2024-10-29",
                     target_roe=10.0, buyback_planned=True)
        oldest = plan(plan_id=1, disclosure_date="2024-08-14")
        c = choose_plan([latest, older, oldest])
        assert c.plan["plan_id"] == 2
        assert c.used_fallback is True

    def test_does_not_fall_back_when_latest_has_even_one_axis(self):
        """최신이 1축이라도 있으면 그것이 회사의 현재 입장 — 과거를 살리지 않는다.

        이 경계가 정책의 핵심이다. 여기서 '더 많은 축'을 좇으면 회사가 축소·철회한
        목표를 우리가 되살리게 된다.
        """
        latest = plan(plan_id=2, disclosure_date="2026-03-31", target_roe=8.0)
        older = plan(plan_id=1, disclosure_date="2024-10-29", target_roe=10.0,
                     target_payout_ratio=30.0, period_start="2024",
                     buyback_planned=True)  # 4축
        c = choose_plan([latest, older])
        assert c.plan["plan_id"] == 2  # 1축짜리 최신을 유지
        assert c.used_fallback is False

    def test_keeps_latest_when_nothing_has_targets(self):
        """전부 0축이면 폴백이 아니다 — 실제로 아무도 목표를 공시하지 않았고,
        그건 순위 불가로 정직하게 남아야 한다(SK하이닉스 형태)."""
        latest = plan(plan_id=2, disclosure_date="2026-03-31")
        older = plan(plan_id=1, disclosure_date="2024-11-27")
        c = choose_plan([latest, older])
        assert c.plan["plan_id"] == 2
        assert c.used_fallback is False

    def test_refiling_follows_the_disclosure_it_points_at(self):
        """우리금융 실측 형태: 최신은 고배당기업 표시용 재공시, 실계획은 그것이 가리킨 공시."""
        c = choose_plan([
            plan(plan_id=3, disclosure_date="2026-03-23", body_signal=REFILING,
                 body_reference_date="2026-02-06"),
            plan(plan_id=2, disclosure_date="2026-02-06", target_roe=9.0),
            plan(plan_id=1, disclosure_date="2024-06-24"),
        ])
        assert c.plan["plan_id"] == 2
        assert c.used_fallback is True

    def test_refiling_without_date_is_skipped(self):
        """하나금융 실측 형태: 재공시인 건 알지만 가리킨 날짜를 못 읽음 → 그 문서를 건너뛴다."""
        c = choose_plan([
            plan(plan_id=3, disclosure_date="2026-03-31", body_signal=REFILING),
            plan(plan_id=2, disclosure_date="2024-10-29", target_roe=10.0),
        ])
        assert c.plan["plan_id"] == 2
        assert c.used_fallback is True

    def test_refiling_chain_is_followed_without_looping(self):
        """재공시가 재공시를 가리켜도 따라가고, 순환 참조에서도 멈춘다."""
        c = choose_plan([
            plan(plan_id=3, disclosure_date="2026-03-23", body_signal=REFILING,
                 body_reference_date="2026-02-06"),
            plan(plan_id=2, disclosure_date="2026-02-06", body_signal=REFILING,
                 body_reference_date="2026-03-23"),  # 되돌아가는 참조
            plan(plan_id=1, disclosure_date="2025-01-10", target_roe=8.0),
        ])
        assert c.plan["plan_id"] == 1  # 순환에 갇히지 않고 실계획까지 내려감

    def test_lone_refiling_is_kept_rather_than_returning_nothing(self):
        """재공시 한 건뿐이면 그것을 그대로 둔다 — 빈 결과보다 '근거 없음'이 낫다."""
        c = choose_plan([
            plan(plan_id=1, disclosure_date="2026-03-31", body_signal=REFILING),
        ])
        assert c.plan["plan_id"] == 1

    def test_body_signal_absent_behaves_as_before(self):
        """신호가 아직 백필되지 않은 행(null)도 기존 규칙대로 동작한다."""
        c = choose_plan([
            plan(plan_id=2, disclosure_date="2026-03-31", body_signal=None),
            plan(plan_id=1, disclosure_date="2024-10-29", target_roe=10.0),
        ])
        assert c.plan["plan_id"] == 1
        assert c.used_fallback is True

    def test_picks_most_recent_among_several_candidates(self):
        """폴백은 '가장 최근의 목표 있는 공시'로 — 더 옛날로 내려가지 않는다."""
        c = choose_plan([
            plan(plan_id=4, disclosure_date="2026-03-31"),
            plan(plan_id=3, disclosure_date="2026-02-06"),
            plan(plan_id=2, disclosure_date="2025-02-07", target_roe=9.0),
            plan(plan_id=1, disclosure_date="2024-06-24", target_roe=10.0),
        ])
        assert c.plan["plan_id"] == 2
        assert c.used_fallback is True
