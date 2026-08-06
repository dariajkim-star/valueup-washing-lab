"""공시 선택 정책 — 최신 우선 + 0축이면 과거 폴백 (2026-07-29 리드 결정).

순수 함수라 DB 없이 검증한다. 이 규칙은 gap·opacity 두 엔진과 서빙이 공유하므로
여기서 깨지면 세 곳이 동시에 틀린다.
"""

from __future__ import annotations

from app.analysis.plan_selection import (
    AXIS_TARGETS,
    NO_TARGETS,
    REFILING,
    choose_plan,
    disclosed_axis_count,
    merge_attachment,
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


class TestMergeAttachment:
    """본문 + 첨부(계획서 PDF) = 그 공시의 유효 목표.

    실측(LG화학 2026-04-01): 본문 0축인 공시에 첨부가 ROE 10.0·배당성향 20.0(p.12)을
    담고 있었다. 합치지 않으면 이미 파싱해 둔 목표를 두고도 그 공시를 0축으로 취급한다.
    """

    def test_attachment_fills_empty_axes(self):
        merged = merge_attachment(
            plan(plan_id=1),
            {"target_roe": 10.0, "target_payout_ratio": 20.0, "parse_error": None},
        )
        assert merged["target_roe"] == 10.0
        assert merged["target_payout_ratio"] == 20.0
        assert disclosed_axis_count(merged) == 2
        assert set(merged["attachment_filled"]) == {"target_roe", "target_payout_ratio"}

    def test_body_wins_on_conflict_and_conflict_is_recorded(self):
        """본문이 우선 — 첨부가 값을 조용히 덮어쓰지 않는다. 충돌은 숨기지 않는다."""
        merged = merge_attachment(
            plan(plan_id=1, target_roe=12.0),
            {"target_roe": 10.0, "parse_error": None},
        )
        assert merged["target_roe"] == 12.0
        assert merged["target_conflicts"] == ["target_roe"]

    def test_unreadable_attachment_is_ignored(self):
        """못 읽은 첨부는 목표로도, 목표 없음으로도 쓰지 않는다."""
        merged = merge_attachment(
            plan(plan_id=1),
            {"target_roe": 10.0, "parse_error": "no_text_layer"},
        )
        assert merged["target_roe"] is None
        assert merged["attachment_filled"] == []

    def test_needs_review_attachment_is_ignored(self):
        """OCR 유래 값은 후보다 — 사람이 승인하기 전에는 채점에 들어가지 않는다.

        실측(우리금융 스파이크): OCR+파서가 ROE 10.0을 맞히면서 동시에 2025 이행
        실적(배당성향 35.0)을 목표로 오인했다. 틀린 non-null은 null보다 위험하다.
        """
        merged = merge_attachment(
            plan(plan_id=1),
            {"target_roe": 10.0, "target_payout_ratio": 35.0,
             "parse_error": None, "needs_review": True},
        )
        assert merged["target_roe"] is None
        assert merged["attachment_filled"] == []

    def test_reviewed_attachment_merges(self):
        """승인되면(needs_review=False) 보통 첨부와 같다."""
        merged = merge_attachment(
            plan(plan_id=1),
            {"target_roe": 10.0, "parse_error": None, "needs_review": False},
        )
        assert merged["target_roe"] == 10.0

    def test_no_attachment_is_a_noop(self):
        merged = merge_attachment(plan(plan_id=1, target_roe=9.0), None)
        assert merged["target_roe"] == 9.0
        assert merged["attachment_filled"] == []

    def test_merged_plan_can_win_selection_without_fallback(self):
        """LG화학 실측 형태: 첨부 결합으로 최신 공시가 유효해져 폴백이 불필요해진다."""
        latest = merge_attachment(
            plan(plan_id=2, disclosure_date="2026-04-01"),
            {"target_roe": 10.0, "target_payout_ratio": 20.0, "parse_error": None},
        )
        older = plan(plan_id=1, disclosure_date="2024-11-22", target_roe=10.0)
        c = choose_plan([latest, older])
        assert c.plan["plan_id"] == 2
        assert c.used_fallback is False


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

    # ── 재공시 참조의 직교 승격 (Story 1.11 T2.5, 파티 비준 2026-08-06) ──
    #
    # 규칙 1의 판정 키가 `body_signal == REFILING`이면, 파서가 좋아져 재공시 문서의
    # 목표가 파싱되는 순간 사다리 1번(축>0)이 라벨을 axis_targets로 덮어 **건너뛰기가
    # 죽는다**. 지금까지 작동한 건 재공시 문서들이 우연히 파싱되지 않았기 때문이다.
    # 그래서 참조 사실을 라벨과 분리해 직교로 본다(attachment_absent와 같은 계열).

    def test_reference_date_is_followed_even_when_label_is_axis_targets(self):
        """서울보증보험 실측: 재공시 사본에 계획이 복사돼 있어 파싱에 성공한 경우.

        라벨은 axis_targets로 바뀌지만 **약속을 한 날은 원공시일**이다. 참조 날짜가
        살아 있으면 라벨과 무관하게 그것이 가리킨 공시로 간다.
        """
        c = choose_plan([
            plan(plan_id=98, disclosure_date="2026-03-31", body_signal=AXIS_TARGETS,
                 body_reference_date="2025-09-30", target_roe=10.0),
            plan(plan_id=99, disclosure_date="2025-09-30", body_signal=AXIS_TARGETS,
                 target_roe=10.0),
        ])
        assert c.plan["plan_id"] == 99
        assert c.used_fallback is True

    def test_axis_targets_without_reference_date_is_untouched(self):
        """보일러플레이트 방어: '변경 시 재공시 할 예정'은 미래 약속이라 날짜가 없다.

        실측 — axis_targets 309건 전부 참조 날짜가 없어 규칙 1이 발동하지 않는다.
        여기서 발동하면 68건이 오폭된다(파티에서 기각된 '사다리 상향'안의 실패 지점).
        """
        c = choose_plan([
            plan(plan_id=2, disclosure_date="2026-03-31", body_signal=AXIS_TARGETS,
                 target_roe=12.0),
            plan(plan_id=1, disclosure_date="2024-10-29", target_roe=8.0),
        ])
        assert c.plan["plan_id"] == 2
        assert c.used_fallback is False

    def test_refiling_without_date_is_still_skipped_after_promotion(self):
        """회귀 방어: 참조 날짜가 없어도 refiling 라벨은 여전히 후보에서 빠진다.

        판정 키를 날짜로 **교체**하면 이 경로가 사라져 실측 4개사(포스코퓨처엠·
        한국전력기술·DB하이텍·한국타이어)의 선택이 바뀐다. 교체가 아니라 **병렬 추가**다.
        """
        c = choose_plan([
            plan(plan_id=3, disclosure_date="2026-03-31", body_signal=REFILING),
            plan(plan_id=1, disclosure_date="2024-10-29", target_roe=10.0),
        ])
        assert c.plan["plan_id"] == 1
        assert c.used_fallback is True

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
