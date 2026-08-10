"""본문 신호 분류 — 실측 3종목이 만든 규칙(2026-07-29).

그날까지 셋이 전부 "미공시 4축"이라는 같은 칸에 있었다. 실데이터 원문을 발췌해
각 분류가 실제 공시에서 나온 것임을 고정한다.
"""

from __future__ import annotations

from app.analysis.plan_signals import (
    AXIS_TARGETS,
    NO_TARGETS,
    OTHER_METRIC,
    REFILING,
    NOTICE,
    UNDISCLOSED,
    UNREADABLE,
    UNSTATED,
    classify_body,
    declares_no_attachment,
    is_notice,
    references_external_plan,
    unrankable_reason,
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

    def test_reference_date_survives_axis_targets(self):
        """[Story 1.11 T2.5 · 파티 비준 2026-08-06] **계약 개정**.

        이전 계약은 `axis_targets`면 `referenced_date is None`이었다. 그 전제는
        "재공시 사본은 어차피 파싱이 안 된다"였고, 1.11이 그 우연을 없앤다 —
        서울보증보험 98처럼 계획이 복사된 재공시는 파싱에 성공한다.

        라벨(`왜 축을 못 채웠나`)과 참조 사실(`어느 공시를 가리키나`)은 **직교**다.
        축을 채웠다고 참조 사실이 사라지면 `choose_plan`이 껍데기 문서를 근거로 삼는다.
        """
        s = classify_body(WOORI_REFILING, {**EMPTY, "target_roe": 10.0})
        assert s.kind == AXIS_TARGETS
        assert s.referenced_date == "2026-02-06"

    def test_axis_targets_without_pointer_keeps_null(self):
        """보일러플레이트 방어 — '변경 시 재공시 할 예정'은 가리킬 날짜가 없다.

        실측: `axis_targets` 309건 전부 참조 날짜 없음. 여기서 날짜가 생기면
        68건이 오폭된다.
        """
        text = "시장상황 변화에 따라 변경될 수 있으며, 변경 시 재공시 할 예정입니다."
        s = classify_body(text, {**EMPTY, "target_roe": 10.0})
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


class TestDeclaresNoAttachment:
    """[2026-08-04 신설 → 2026-08-05 직교 컬럼으로 이관] 회사가 첨부가 없다고 명시했는가.

    실측 근거: no_targets 175건 전수 판독에서 101개사가 같은 문장을 썼고, 다음날 전
    코퍼스를 세니 **212건**이었다. 처음엔 이 사실을 `body_signal`의 한 칸
    (`exempt_short_form`)에 넣었는데 그건 우선순위 사다리라 **목표를 공시한 회사가 첨부
    부존재를 함께 선언하면 위쪽 신호에 가려 샜다**(실측 8건). 그래서 판정을 사다리에서
    떼어내 독립 함수로 두고, 저장도 직교 컬럼으로 옮겼다(마이그 0031).

    이 클래스가 고정하는 계약: **두 축은 서로를 가리지 않는다.**
    """

    HIGH_DIV = (
        "5. 기타 투자판단과 관련한 중요사항\n"
        "1. 조세특례제한법 제104조의27에 따른 고배당기업에 해당하여 "
        "별도의 기업가치 제고 계획 첨부 없이 주요 내용을 기재하였습니다."
    )

    def test_no_attachment_declaration(self):
        assert declares_no_attachment(self.HIGH_DIV) is True

    def test_spacing_variant(self):
        """'첨부 없이'와 '첨부없이'가 둘 다 실재한다(총계 라벨 갈림과 같은 계열)."""
        assert declares_no_attachment(
            self.HIGH_DIV.replace("첨부 없이", "첨부없이")
        ) is True

    def test_omission_variant(self):
        """신라교역형 — '첨부서류를 생략한 약식 공시'."""
        text = "4. 본 공시는 기업가치 제고 계획 첨부서류를 생략한 약식 공시입니다."
        assert declares_no_attachment(text) is True

    def test_real_reference_is_not_a_declaration(self):
        """진짜 첨부 참조는 선언이 아니다 — 이쪽이 첨부 수집의 실제 대상이다."""
        text = "상세한 내용은 첨부된 '기업가치 제고 계획'을 참고하시기 바랍니다."
        assert declares_no_attachment(text) is False
        assert classify_body(text, EMPTY).kind == NO_TARGETS

    def test_empty_text(self):
        assert declares_no_attachment(None) is False
        assert declares_no_attachment("") is False

    # ── 직교성: body_signal이 무엇이든 선언은 선언이다(2026-08-05 결함의 재발 방지) ──

    def test_axis_targets_does_not_hide_declaration(self):
        """축을 확보한 공시도 첨부는 안 붙였을 수 있다 — 실측 102건이 이 조합이다."""
        assert classify_body(self.HIGH_DIV, {"target_roe": 10.0}).kind == AXIS_TARGETS
        assert declares_no_attachment(self.HIGH_DIV) is True

    def test_other_metric_does_not_hide_declaration(self):
        """실측 6건(도화엔지니어링·제주은행·대한유화·아세아시멘트·HL디앤아이한라·
        코리안리) — 이 조합이 워크리스트에 새어 있던 경로다."""
        text = self.HIGH_DIV + "\n'28년 EBITDA Margin 10% 중반 이상 목표"
        assert classify_body(text, EMPTY).kind == OTHER_METRIC
        assert declares_no_attachment(text) is True

    def test_refiling_does_not_hide_declaration(self):
        """실측 2건(신도리코 등). 여기서 우선순위를 뒤집었다면 **선택 규칙이 깨진다** —
        재공시가 가리킨 실제 계획을 못 따라가게 된다. 그래서 축을 나눈 것이다."""
        text = self.HIGH_DIV + "\n旣공시(2026.2.6) 내용 참조"
        assert classify_body(text, EMPTY).kind == REFILING
        assert declares_no_attachment(text) is True


# ── code-review 2026-08-07 결정 ⑦: 실재하는 날짜만 내보낸다 ──


class TestReferencedDateValidity:
    """`_referenced_date`에 날짜 검증이 없어 ISO처럼 생긴 **무효 문자열**이 나왔다.

    무효 날짜는 `choose_plan`에서 어떤 공시와도 매칭되지 않아 조용히 "가리켰는데 못 찾음"
    경로로 떨어진다. 못 읽은 것은 못 읽었다고 말하는 게 낫다(NFR2).
    1.11 이전에는 이 추출이 사다리 2번 안에 있어 축>0 문서에서는 돌지도 않았다 —
    노출면이 313건으로 넓어졌기 때문에 이제 이 검증이 필요하다.
    """

    def test_impossible_day_is_rejected(self):
        s = classify_body("旣공시(2026.2.30) 내용 참조", EMPTY)
        assert s.referenced_date is None

    def test_impossible_month_is_rejected(self):
        s = classify_body("기공시(2026.13.45) 참조", EMPTY)
        assert s.referenced_date is None

    def test_zero_month_and_day_rejected(self):
        s = classify_body("기공시(2026.0.0) 참조", EMPTY)
        assert s.referenced_date is None

    def test_valid_date_still_extracted(self):
        """정상 경로는 그대로 — 실측 4건이 전부 이 형태다."""
        s = classify_body("旣공시(2026.2.6) 내용 참조", EMPTY)
        assert s.kind == REFILING
        assert s.referenced_date == "2026-02-06"

    def test_leap_day_is_valid(self):
        """2026-02-29는 없지만 2024-02-29는 있다 — 달력을 쓰지 자릿수만 세지 않는다."""
        assert classify_body("旣공시(2024.2.29) 참조", EMPTY).referenced_date == "2024-02-29"
        assert classify_body("旣공시(2026.2.29) 참조", EMPTY).referenced_date is None


# ── Story 6.4 / FR-15: 순위 불가의 세 범주 ──


class TestUnrankableReason:
    """순위 불가가 **회사가 안 낸 것**인지 **우리가 못 읽은 것**인지 가른다.

    누락이 기준축이 되면(PRD §1.1) 이 둘은 같은 칸에 있을 수 없다 — 전자는 찾던 신호
    그 자체이고, 후자는 우리 파이프라인의 한계다. `attachments/README.md`가 이미
    계약으로 갖고 있던 구분을 부축에서 주축으로 올린 것이다.
    """

    ZERO = dict(EMPTY)  # 4축 전무 = 순위 불가
    REF = "상세한 내용은 첨부된 '2024년 SK하이닉스 기업가치 제고 계획'을 참고하시기 바랍니다."
    DECL = ("조세특례제한법 제104조의27에 따른 고배당기업에 해당하여 별도의 기업가치 "
            "제고 계획 첨부 없이 주요 내용을 기재하였습니다.")

    def _plan(self, **kw):
        return {**self.ZERO, "raw_text": None, "attachment_absent": None, **kw}

    def test_rankable_plan_has_no_reason(self):
        """축이 하나라도 있으면 순위 대상 — 사유를 묻지 않는다."""
        assert unrankable_reason(self._plan(target_roe=10.0)) is None

    def test_declaration_is_undisclosed(self):
        """실측 110건. 회사가 첨부 없다고 **직접 말했다** → 미공시는 신호다."""
        p = self._plan(raw_text=self.DECL, attachment_absent=True)
        assert unrankable_reason(p) == UNDISCLOSED

    def test_attachment_reference_is_unreadable(self):
        """실측 29건. 받으러 갈 문서가 있다 → 우리 한계, 워크리스트로 간다."""
        p = self._plan(raw_text=self.REF, attachment_absent=False)
        assert unrankable_reason(p) == UNREADABLE

    def test_no_evidence_is_unstated(self):
        """실측 67건. **근거가 없으면 미공시로 세지 않는다** — 이게 AC 4다.

        모르는 것에 이름을 붙이는 순간 그것이 세탁이다(NFR2).
        """
        p = self._plan(raw_text="기업가치 제고 계획을 공시합니다.", attachment_absent=False)
        assert unrankable_reason(p) == UNSTATED

    def test_missing_raw_text_is_unstated_not_undisclosed(self):
        """원문이 없으면 **판정 보류**다. 없는 것을 '회사가 안 냈다'로 읽지 않는다."""
        assert unrankable_reason(self._plan()) == UNSTATED

    def test_declaration_wins_over_reference_ordering(self):
        """순서 근거: 회사가 직접 쓴 선언이 가장 강한 증거다.

        실측상 둘이 공존하는 행은 **0건**이라 이 순서는 아무것도 가리지 않는다
        (라벨링 기준서 §2-F — 상상한 경계가 아니라 세어본 결과).
        """
        p = self._plan(raw_text=self.DECL + " " + self.REF, attachment_absent=True)
        assert unrankable_reason(p) == UNDISCLOSED


class TestReferencesExternalPlan:
    """어휘 선정에 규율이 있다 — **변별력을 먼저 쟀다**(전 코퍼스 519건)."""

    def test_real_reference_forms(self):
        for text in (
            "상세한 내용은 첨부된 '기업가치 제고 계획'을 참고하시기 바랍니다.",
            "세부사항은 첨부된 '2025년 ㈜케이씨씨 기업가치 제고 계획' 파일을 참고하시기",
            "2025년 9월 25일 공시한 기업가치 제고 계획에 첨부한 내용과 동일합니다.",
        ):
            assert references_external_plan(text) is True, text

    def test_standard_form_fields_are_not_references(self):
        """`게재일시`·`관련 웹페이지`는 519건 중 **463건**에 있는 DART 표준 서식 필드다.

        2026-07-28에 `is_unrankable`의 참조 검사를 폐기한 이유가 정확히 이것이었고
        (불투명순 1·2·3등이 전부 오탐), 같은 함정을 열흘 만에 다시 밟을 뻔했다.
        """
        assert references_external_plan("5. 관련 자료 \n게재일시 \n- \n관련 웹페이지 \n-") is False
        assert references_external_plan("관련 웹페이지 https://example.com/ir") is False

    def test_declaration_is_not_a_reference(self):
        """`첨부서류`는 선언 문구 `첨부서류를 생략한`의 **부분문자열**이다.

        어휘에 넣었더니 선언·참조가 9건 공존했다 — 전부 이 오탐이었고, 빼니 0건이 됐다.
        """
        decl = "본 공시는 기업가치 제고 계획 첨부서류를 생략한 약식 공시입니다."
        assert references_external_plan(decl) is False
        assert declares_no_attachment(decl) is True

    def test_empty_text(self):
        assert references_external_plan(None) is False
        assert references_external_plan("") is False


# ── OQ-4 종결 2026-08-07: 예고(안내공시)는 네 번째 범주 ──


class TestNotice:
    """예고는 **미공시가 아니라 아직 시점이 안 된 것**이다.

    처음 셋으로 갈랐을 때 무언급이 67건이었는데 **그중 56건이 예고**였다.
    "판정 보류"라던 통의 84%가 실은 애매하지 않았고, 우리가 제목을 안 봤을 뿐이다.
    """

    TITLE = ("우리금융지주/기업가치 제고 계획 예고(안내공시)/(2024.06.24)"
             "기업가치 제고 계획 예고(안내공시)")
    # 진짜 계획이 **자기 예고를 참조**하는 형태 — 오탐의 원천(실측 48건)
    RELATED = "※ 관련공시 \n2024-09-04 기업가치 제고 계획 예고(안내공시)"

    def test_title_form_is_a_notice(self):
        assert is_notice(self.TITLE) is True

    def test_related_disclosure_list_is_not_a_notice(self):
        """**단순 포함으로 잡으면 axis_targets 40건이 예고로 뒤집힌다.**

        전 코퍼스 519건에서 `예고(안내공시)` 문자열은 104건에 있지만 진짜 예고는 56건뿐이고,
        나머지 48건은 목표를 다 공시한 회사가 자기 예고를 관련공시로 나열한 것이다.
        `게재`·`관련 웹페이지`와 같은 계열의 함정이며, 여기서는 **제목 서식**이 갈랐다.
        """
        assert is_notice(self.RELATED) is False

    def test_notice_is_its_own_unrankable_reason(self):
        empty = {**EMPTY, "raw_text": self.TITLE, "attachment_absent": False}
        assert unrankable_reason(empty) == NOTICE

    def test_plan_referencing_its_notice_is_not_labelled_notice(self):
        """관련공시 목록만 가진 축=0 공시는 여전히 무언급이다(근거가 없으므로)."""
        empty = {**EMPTY, "raw_text": self.RELATED, "attachment_absent": False}
        assert unrankable_reason(empty) == UNSTATED

    def test_declaration_still_wins_over_notice(self):
        """사다리 순서 — 회사가 직접 쓴 선언이 먼저다. 실측상 공존 0건이라 무해하다."""
        text = self.TITLE + " 첨부 없이 주요 내용을 기재하였습니다."
        empty = {**EMPTY, "raw_text": text, "attachment_absent": True}
        assert unrankable_reason(empty) == UNDISCLOSED

    def test_empty_text(self):
        assert is_notice(None) is False
        assert is_notice("") is False
