"""본문 신호 분류 — 실측 3종목이 만든 규칙(2026-07-29).

그날까지 셋이 전부 "미공시 4축"이라는 같은 칸에 있었다. 실데이터 원문을 발췌해
각 분류가 실제 공시에서 나온 것임을 고정한다.
"""

from __future__ import annotations

from app.analysis.plan_signals import (
    AXIS_TARGETS,
    EXEMPT_SHORT_FORM,
    NO_TARGETS,
    OTHER_METRIC,
    REFILING,
    classify_body,
)

EMPTY = {
    "target_roe": None,
    "target_payout_ratio": None,
    "target_total_return_ratio": None,
    "period_start": None,
    "buyback_planned": None,
}

# ── 실데이터 발췌 (2026-07-29 다운로드 원문) ──

LG_ENSOL = """3. 목표설정
① '23년 대비 '28년 매출 2배 성장
② '28년 EBITDA Margin 10% 중반 이상
(IRA 효과 제외 기준)
③ 안정적인 잉여현금흐름 창출을 통한 환원 가능 재원 마련
5. 기타 투자판단과 관련한 중요사항
가. 상세한 내용은 첨부된 'LG에너지솔루션 기업가치 제고 계획'을 참고하시기 바랍니다."""

SK_HYNIX = """3. 목표 설정
□ 균형잡힌 CapEx Discipline 실행 □ 독보적인 Tech Leadership 구축
4. 계획 수립
① CapEx Discipline : CapEx/Revenue 30% 중반 목표 (3개년 이동평균)
③ 재무 건전성 강화 : 재무관리 방향성 및 신규 주주환원 정책 제시
- 보다 자세한 내용은 첨부된 '2024년 SK하이닉스 기업가치 제고 계획'을 참고하시기를 바랍니다."""

WOORI_REFILING = """2. 주요 내용
- 당사 조세특례제한법 제104조의27에 따른 고배당기업 요건 충족 공시
- 「2026년 우리금융그룹 기업가치 제고계획」은 旣공시(2026.2.6) 내용 참조
직전 사업연도 (2025) 배당성향(%)
32.0
전전 사업연도 대비 직전 사업연도 이익배당금액 증가율(%)
12.1"""


class TestAxisTargetsWins:
    def test_any_axis_found_beats_other_classifications(self):
        """축을 하나라도 확보했으면 그것이 사실 — 재공시 문구가 섞여도 마찬가지."""
        s = classify_body(WOORI_REFILING, {**EMPTY, "target_roe": 10.0})
        assert s.kind == AXIS_TARGETS
        assert s.referenced_date is None


class TestOtherMetric:
    def test_lg_ensol_disclosed_targets_just_not_ours(self):
        """LG엔솔은 부실 공시가 아니다 — 매출·EBITDA로 명확히 약속했다."""
        assert classify_body(LG_ENSOL, EMPTY).kind == OTHER_METRIC

    def test_sk_hynix_capex_target(self):
        assert classify_body(SK_HYNIX, EMPTY).kind == OTHER_METRIC

    def test_marker_must_be_on_the_same_line_as_the_number(self):
        """다른 줄의 '목표'를 빌려와 실적 숫자를 목표로 만들지 않는다."""
        text = "향후 목표를 아래와 같이 정한다\n직전 사업연도 배당성향 32.0%"
        assert classify_body(text, EMPTY).kind == NO_TARGETS


class TestRefiling:
    def test_woori_points_at_prior_disclosure(self):
        s = classify_body(WOORI_REFILING, EMPTY)
        assert s.kind == REFILING
        assert s.referenced_date == "2026-02-06"

    def test_hyphen_and_hangul_variants(self):
        for text, expected in [
            ("기공시(2026-02-06) 내용 참조", "2026-02-06"),
            ("旣공시（2025.12.1） 참조", "2025-12-01"),
            ("旣공시 2024/3/5 내용 참조", "2024-03-05"),
        ]:
            s = classify_body(text, EMPTY)
            assert s.kind == REFILING, text
            assert s.referenced_date == expected, text

    def test_refiling_without_readable_date_keeps_null(self):
        """가리킨 날짜를 못 읽으면 추측하지 않는다 — null이 정직하다."""
        s = classify_body("본 공시는 재공시입니다.", EMPTY)
        assert s.kind == REFILING
        assert s.referenced_date is None

    def test_actual_targets_outrank_bare_refiling_word(self):
        """'재공시'라는 단어가 있어도 수치 목표가 있으면 다른 지표 공시로 본다."""
        text = "재공시 안내\n'28년 EBITDA Margin 10% 중반 이상"
        assert classify_body(text, EMPTY).kind == OTHER_METRIC


class TestNoTargets:
    def test_pure_cover_notice(self):
        text = "상세한 내용은 첨부된 계획을 참고하시기 바랍니다."
        assert classify_body(text, EMPTY).kind == NO_TARGETS

    def test_empty_and_none(self):
        assert classify_body(None, EMPTY).kind == NO_TARGETS
        assert classify_body("", EMPTY).kind == NO_TARGETS


class TestExemptShortForm:
    """[2026-08-04] 회사가 첨부가 없다고 명시한 약식 공시 — 첨부 목록에서 빼기 위한 신호.

    실측 근거: no_targets 175건 전수 판독에서 101개사가 같은 문장을 썼다.
    나누는 유일한 이유는 **행동이 다르다**는 것 — 없는 문서를 찾으러 보내지 않는다.
    """

    HIGH_DIV = (
        "5. 기타 투자판단과 관련한 중요사항\n"
        "1. 조세특례제한법 제104조의27에 따른 고배당기업에 해당하여 "
        "별도의 기업가치 제고 계획 첨부 없이 주요 내용을 기재하였습니다."
    )

    def test_no_attachment_declaration(self):
        assert classify_body(self.HIGH_DIV, EMPTY).kind == EXEMPT_SHORT_FORM

    def test_spacing_variant(self):
        """'첨부 없이'와 '첨부없이'가 둘 다 실재한다(총계 라벨 갈림과 같은 계열)."""
        assert classify_body(
            self.HIGH_DIV.replace("첨부 없이", "첨부없이"), EMPTY
        ).kind == EXEMPT_SHORT_FORM

    def test_omission_variant(self):
        """신라교역형 — '첨부서류를 생략한 약식 공시'."""
        text = "4. 본 공시는 기업가치 제고 계획 첨부서류를 생략한 약식 공시입니다."
        assert classify_body(text, EMPTY).kind == EXEMPT_SHORT_FORM

    def test_real_reference_stays_no_targets(self):
        """진짜 첨부 참조는 갈라내지 않는다 — 이쪽이 첨부 수집의 실제 대상이다."""
        text = "상세한 내용은 첨부된 '기업가치 제고 계획'을 참고하시기 바랍니다."
        assert classify_body(text, EMPTY).kind == NO_TARGETS

    def test_axis_targets_still_win(self):
        """축을 확보했으면 첨부 부존재 선언이 있어도 axis_targets다(우선순위 불변)."""
        sig = classify_body(self.HIGH_DIV, {"target_roe": 10.0})
        assert sig.kind == AXIS_TARGETS

    def test_other_metric_outranks(self):
        """다른 지표로라도 목표를 공시했으면 그 사실이 먼저다."""
        text = self.HIGH_DIV + "\n'28년 EBITDA Margin 10% 중반 이상 목표"
        assert classify_body(text, EMPTY).kind == OTHER_METRIC
