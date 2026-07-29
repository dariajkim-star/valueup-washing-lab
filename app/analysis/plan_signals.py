"""공시 본문이 **왜** 우리 축을 못 채웠는가 — 본문 신호 분류.

2026-07-29 실측이 만든 모듈이다. 그날까지 아래 셋이 전부 "미공시 4축"이라는 같은 칸에
있었는데, 실제로는 서로 다른 세 가지였다:

    LG에너지솔루션  '23년 대비 '28년 매출 2배 · '28년 EBITDA Margin 10% 중반 이상
                    → 목표를 **명확히 공시했다**. 우리 자에 그 눈금이 없을 뿐.
    SK하이닉스      CapEx/Revenue 30% 중반 목표 (3개년 이동평균)
                    → 위와 같은 유형.
    우리금융지주    "「2026년 우리금융그룹 기업가치 제고계획」은 旣공시(2026.2.6) 내용 참조"
                    → 계획이 아니라 **다른 공시를 가리키는 재공시**(고배당기업 표시용).

이 구분이 없으면 두 가지를 잘못한다:
  1. 화면이 "순위 불가"라고만 말해, 사용자가 '회사가 부실 공시'로 읽는다. LG엔솔은
     부실하게 공시한 게 아니라 **다른 지표로** 공시했다.
  2. 첨부 작업 목록이 엉뚱한 공시를 가리킨다. 우리금융에 필요한 건 03-23이 아니라
     그것이 지목한 02-06이다.

설계 원칙(레아): 규칙을 넓히지 말고, **행동이 달라지는 만큼만** 나눈다.
  - refiling         → 선택 규칙이 바뀐다(가리킨 공시로 간다).
  - other_metric     → 화면 문구가 바뀐다(+ 첨부를 받아도 우리 축이 안 나올 수 있다는 신호).
  - axis_targets     → 정상 경로.
  - no_targets       → 본문에 숫자 목표 자체가 없음(진짜 표지 통지문).
행동이 같은 상태는 만들지 않았다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# 상수는 plan_selection이 소유한다(선택 규칙이 refiling을 알아야 하는데 그쪽이 이 모듈을
# import하면 순환이 된다). 여기서는 판정 로직만 갖고 어휘는 빌려 쓴다.
from app.analysis.plan_selection import (  # noqa: F401 — 재수출(호출부 편의)
    AXIS_TARGETS,
    NO_TARGETS,
    OTHER_METRIC,
    REFILING,
    disclosed_axis_count,
)

# 목표를 뜻하는 표지. parse_targets의 _TARGET_MARK와 같은 계열이지만 여기선 **어느 지표든**
# 상관없이 "목표가 쓰여 있는가"만 본다.
_TARGET_MARKER = r"(?:목표|지향|이상|달성|확대|중반)"
# 수치 목표의 형태: 퍼센트 또는 배수. (원·주 단위 금액은 목표보다 실적 표기가 압도적이라 제외)
_NUMERIC = re.compile(r"\d+(?:\.\d+)?\s*(?:%|배)")
# 숫자 주변 이 폭 안에 표지가 있으면 '목표 수치'로 본다(개행은 넘지 않는다 — 다른 항목 침범 방지).
_WINDOW = 25

# 재공시 참조: "旣공시(2026.2.6) 내용 참조" / "기공시(2026-02-06)" 등.
# 한자 旣와 한글 기 둘 다, 구분자는 . - / 허용.
_REFILING_REF = re.compile(
    r"(?:旣|기)\s*공시\s*[\(（]?\s*(20\d{2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})"
)
# 참조 날짜가 본문에 없을 때를 위한 약한 신호(날짜 없이 '재공시'만 언급).
_REFILING_WORD = re.compile(r"재공시|기공시한 경우|旣공시")


@dataclass(frozen=True)
class BodySignal:
    kind: str
    referenced_date: str | None = None  # refiling일 때 가리킨 공시일(ISO), 못 읽으면 None


def _has_numeric_target(text: str) -> bool:
    """본문에 '목표성 수치'가 있는가 — 지표 종류는 묻지 않는다.

    숫자 앞뒤 좁은 창에 목표 표지가 있어야 한다. 실적 표(예: "직전 사업연도 배당성향 32.0")는
    표지가 없어 걸리지 않는다 — 우리금융 03-23이 실제로 그 케이스다.
    """
    for m in _NUMERIC.finditer(text):
        lo = max(0, m.start() - _WINDOW)
        hi = min(len(text), m.end() + _WINDOW)
        around = text[lo:hi]
        # 개행 너머의 표지를 빌려오지 않도록 숫자가 속한 줄 범위로 자른다
        seg_start = around.rfind("\n", 0, m.start() - lo)
        seg_end = around.find("\n", m.end() - lo)
        segment = around[seg_start + 1 if seg_start >= 0 else 0:
                         seg_end if seg_end >= 0 else len(around)]
        if re.search(_TARGET_MARKER, segment):
            return True
    return False


def classify_body(raw_text: str | None, targets: Mapping[str, Any]) -> BodySignal:
    """본문 원문 + 그 본문에서 뽑은 목표 → 신호.

    우선순위: 축 확보 > 재공시 > 다른 지표 > 목표 없음.
    축을 하나라도 확보했으면 그것이 사실이므로 다른 분류를 붙이지 않는다(재공시 문구가
    섞여 있어도 마찬가지 — 실제로 쓸 값이 있으면 그 공시가 근거다).
    """
    if disclosed_axis_count(targets) > 0:
        return BodySignal(AXIS_TARGETS)

    text = raw_text or ""

    m = _REFILING_REF.search(text)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        return BodySignal(REFILING, referenced_date=f"{y}-{mo:02d}-{d:02d}")

    if _REFILING_WORD.search(text) and not _has_numeric_target(text):
        # 재공시라고 말하는데 가리킨 날짜를 못 읽은 경우 — 날짜는 null로 정직하게 둔다.
        return BodySignal(REFILING)

    if _has_numeric_target(text):
        return BodySignal(OTHER_METRIC)

    return BodySignal(NO_TARGETS)


# ── 관련 웹페이지 URL 추출(0019) ──
# DART 첨부 경로가 닫힌 뒤 남은 길. 회사가 규제 공시에서 **스스로 지목한** 주소이므로
# 크롤링이 아니라 '공시가 준 링크'다.
_URL = r"https?://[^\s\"'<>)\]]+"
# '관련 웹페이지' 라벨 뒤에 오는 URL을 우선한다 — 본문 어디에나 있는 URL(예: 관계사
# 링크)을 계획 출처로 오인하지 않기 위해. 라벨과 URL 사이에 표 마크업 잔재가 낄 수 있어
# 넉넉한 창을 두되 다른 URL을 건너뛰지는 않는다.
_LABELED_URL = re.compile(r"관련\s*웹\s*페이지[^h]{0,200}?(" + _URL + ")")
_ANY_URL = re.compile(_URL)
# 우리 자신(DART)으로 되돌아가는 링크는 IR 출처가 아니다.
_SELF_HOSTS = ("dart.fss.or.kr", "fss.or.kr", "kind.krx.co.kr")


def extract_related_url(raw_text: str | None) -> str | None:
    """공시 본문에서 '관련 웹페이지' URL. 없으면 None(추측하지 않는다).

    라벨 매칭을 먼저 시도하고, 실패하면 본문의 첫 외부 URL로 폴백한다. 폴백을 두는 이유는
    서식이 회사마다 조금씩 다르기 때문이고, DART 자기 링크는 양쪽 모두에서 제외한다.
    """
    text = raw_text or ""
    for rx, group in ((_LABELED_URL, 1), (_ANY_URL, 0)):
        for m in rx.finditer(text):
            url = m.group(group).rstrip(".,;)")
            if any(h in url for h in _SELF_HOSTS):
                continue
            return url
    return None


# 화면·CLI에서 쓰는 사람 말. 코드 상수와 표시 문구를 한 곳에 묶어 둘이 갈라지지 않게 한다.
SIGNAL_LABEL = {
    AXIS_TARGETS: "본문에서 목표 확보",
    OTHER_METRIC: "다른 지표로 공시(우리 축 밖)",
    REFILING: "재공시 — 다른 공시를 가리킴",
    NO_TARGETS: "본문에 목표 없음",
}
