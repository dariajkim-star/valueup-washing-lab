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
  - refiling           → 선택 규칙이 바뀐다(가리킨 공시로 간다).
  - other_metric       → 화면 문구가 바뀐다(+ 첨부를 받아도 우리 축이 안 나올 수 있다는 신호).
  - axis_targets       → 정상 경로.
  - no_targets         → 본문에 숫자 목표 자체가 없음(진짜 표지 통지문).
행동이 같은 상태는 만들지 않았다.

■ 첨부 부존재는 **직교한 사실**이다 (2026-08-05 재측정이 전날의 칸 선택을 정정)
2026-08-04에 `no_targets` 175건을 전수 판독해 한 칸에 이유가 셋 들어 있음을 확인했다:

    101개사  "조세특례제한법 제104조의27에 따른 고배당기업에 해당하여 별도의
             기업가치 제고 계획 **첨부 없이** 주요 내용을 기재하였습니다."
             → 회사가 **첨부가 없다고 직접 말했다.** 받으러 갈 곳이 없다.
     13개사  "상세한 내용은 **첨부된** '…기업가치 제고 계획'을 참고하시기 바랍니다."
             → 진짜 참조. 이것이 첨부 수집의 실제 대상이다.
     57건    첨부 무언급 — 그냥 짧은 통지문.

그날의 처방은 `body_signal`에 `exempt_short_form`을 신설하는 것이었다. **처방은 맞고
칸이 틀렸다.** 다음날 전 코퍼스를 세어보니 첨부 부존재를 선언한 공시는 101이 아니라
**212건**이고, 그중 `exempt_short_form`으로 잡힌 건 102건뿐이었다:

    axis_targets        102   ← 축까지 공시한 회사도 첨부는 안 붙였다
    exempt_short_form   102
    other_metric          6   ← 워크리스트가 여전히 부르고 있었다
    refiling              2   ← 〃 (신도리코)

`classify_body`는 우선순위 사다리이고 exempt는 그 **맨 아래**였다. 그래서 "목표가 있는"
공시가 첨부 부존재를 선언하면 위쪽 신호에 가려 새어나갔다 — 어제 고친 결함이 8건 남아
있었던 것이다(그중 7건이 워크리스트에 실려 있었다).

**우선순위를 올리는 것은 오답이다.** `refiling`은 선택 규칙을 바꾸는 신호라(가리킨
공시로 이동) exempt로 덮으면 신도리코가 가리킨 실제 계획을 못 따라간다. 두 사실이
경쟁하는 게 아니라 **서로 다른 질문에 답한다**:

    body_signal        "이 본문이 왜 우리 4축을 못 채웠나"
    attachment_absent  "받으러 갈 문서가 존재하나"

그래서 후자를 `valueup_plan.attachment_absent` 직교 컬럼으로 옮겼다(마이그 0031).
판정 함수는 `declares_no_attachment` 하나뿐이며, 수집·백필·워크리스트가 그것만 부른다
(어제 `lookahead.py`에서 배운 단일 정의처 — 복제하면 갈라진다).

**부실 공시로 읽지 않는다.** 이들은 자기 자격을 근거로 약식으로 냈다고 명시한 것이고,
"본문에 목표가 없다"는 사실은 같아도 **그 이유가 제도 쪽에 있다.** 순위에서는 이미
`is_unrankable`로 제외돼 벌점이 없다 — 이 변경도 **점수를 건드리지 않고 작업 목록과
화면 문구만 고친다.**
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

# 상수는 plan_selection이 소유한다(선택 규칙이 refiling을 알아야 하는데 그쪽이 이 모듈을
# import하면 순환이 된다). 여기서는 판정 로직만 갖고 어휘는 빌려 쓴다.
from app.analysis.plan_selection import (  # noqa: F401 — 재수출(호출부 편의)
    AXIS_TARGETS,
    NO_TARGETS,
    OTHER_METRIC,
    REFILING,
    disclosed_axis_count,
    is_unrankable,
)

logger = logging.getLogger(__name__)

# 목표를 뜻하는 표지. parse_targets의 _TARGET_MARK와 같은 계열이지만 여기선 **어느 지표든**
# 상관없이 "목표가 쓰여 있는가"만 본다.
_TARGET_MARKER = r"(?:목표|지향|이상|달성|확대|중반)"
# 수치 목표의 형태: 퍼센트 또는 배수. (원·주 단위 금액은 목표보다 실적 표기가 압도적이라 제외)
_NUMERIC = re.compile(r"\d+(?:\.\d+)?\s*(?:%|배)")
# 숫자 주변 이 폭 안에 표지가 있으면 '목표 수치'로 본다(개행은 넘지 않는다 — 다른 항목 침범 방지).
_WINDOW = 25

# 첨부 부존재 선언(2026-08-04 실측, 2026-08-05 직교 컬럼으로 이관).
# 회사가 본문에서 **첨부가 없다고 직접 말한 경우**다:
#   "조세특례제한법 제104조의27에 따른 고배당기업에 해당하여 별도의 기업가치 제고 계획
#    첨부 없이 주요 내용을 기재하였습니다."   ← 101개사가 이 형태(공백 유무만 다름)
#   "본 공시는 기업가치 제고 계획 첨부서류를 생략한 약식 공시입니다."  ← 신라교역형
# 공백을 모두 지우고 비교한다 — '첨부 없이'/'첨부없이'가 둘 다 실재한다(총계 라벨 갈림과 같은 계열).
_NO_ATTACHMENT_DECL = ("첨부없이", "첨부를생략", "첨부서류를생략", "첨부생략")

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


def _squeeze(text: str) -> str:
    """공백 전부 제거 — 같은 문장의 공백 변형('첨부 없이'/'첨부없이')을 한 형태로 본다."""
    return re.sub(r"\s+", "", text)


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


def _referenced_date(text: str) -> str | None:
    """본문이 **가리키는 공시일** — 라벨과 무관한 사실이므로 사다리 밖에서 뽑는다.

    [Story 1.11 T2.5 · 파티 비준 2026-08-06] 이전에는 이 추출이 사다리 2번 안에 있어
    축>0인 공시에서는 **실행조차 되지 않았다**. 그 설계가 지금까지 버틴 이유는 재공시
    사본이 **우연히** 파싱되지 않았기 때문이고(축=0이라 사다리 1번을 통과), 1.11이 그
    우연을 없앤다 — 계획이 복사된 재공시(서울보증보험 98)는 파싱에 성공한다.

    두 사실은 서로 다른 질문에 답한다(`attachment_absent`와 같은 계열):
        body_signal        "이 본문이 왜 우리 4축을 못 채웠나"
        referenced_date    "이 문서가 어느 공시를 가리키나"
    축을 채웠다고 참조 사실이 사라지면 `choose_plan`이 껍데기를 근거로 삼는다.

    날짜가 **없는** 재공시 문구("변경 시 재공시 할 예정")는 미래 약속이라 여기서 None이다
    — 실측상 그것이 보일러플레이트 68건을 오폭에서 지키는 눈금이다.
    """
    m = _REFILING_REF.search(text)
    if not m:
        return None
    y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
    # [code-review 2026-08-07] 실재하는 날짜만 내보낸다. 이전에는 검증이 없어
    # `旣공시(2026.2.30)` → `'2026-02-30'`, `기공시(2026.13.45)` → `'2026-13-45'` 같은
    # **ISO처럼 생긴 무효 문자열**이 DB에 적재됐다. 무효 날짜는 `choose_plan`에서 어떤
    # 공시와도 매칭되지 않아 조용히 "가리켰는데 못 찾음" 경로로 떨어진다 —
    # 못 읽은 것을 못 읽었다고 말하는 게 낫다(NFR2).
    try:
        return date(int(y), mo, d).isoformat()
    except ValueError:
        logger.debug("참조 날짜가 실재하지 않음: %s.%s.%s", y, mo, d)
        return None


def classify_body(raw_text: str | None, targets: Mapping[str, Any]) -> BodySignal:
    """본문 원문 + 그 본문에서 뽑은 목표 → 신호.

    우선순위: 축 확보 > 재공시 > 다른 지표 > 목표 없음.
    축을 하나라도 확보했으면 그것이 사실이므로 다른 분류를 붙이지 않는다(재공시 문구가
    섞여 있어도 마찬가지 — 실제로 쓸 값이 있으면 그 공시가 근거다).

    **단, 참조 날짜는 라벨과 직교하므로 어느 분기에서든 보존한다**(`_referenced_date`).
    """
    text = raw_text or ""
    ref = _referenced_date(text)

    if disclosed_axis_count(targets) > 0:
        return BodySignal(AXIS_TARGETS, referenced_date=ref)

    if ref:
        return BodySignal(REFILING, referenced_date=ref)

    if _REFILING_WORD.search(text) and not _has_numeric_target(text):
        # 재공시라고 말하는데 가리킨 날짜를 못 읽은 경우 — 날짜는 null로 정직하게 둔다.
        return BodySignal(REFILING)

    if _has_numeric_target(text):
        return BodySignal(OTHER_METRIC)

    return BodySignal(NO_TARGETS)


def declares_no_attachment(raw_text: str | None) -> bool:
    """본문이 **첨부가 없다고 직접 선언**했는가 — `attachment_absent`의 단일 정의처.

    `classify_body`와 **독립**이다. 공시가 축을 몇 개 채웠든, 재공시든, 다른 지표로
    공시했든, "첨부 없이 기재했다"는 문장은 그것대로 참이다(실측: 212건 중 102건이
    axis_targets와 공존). 그래서 우선순위 사다리에 끼우지 않고 따로 묻는다.

    True로 읽는 유일한 근거는 **회사가 쓴 문장**이다 — 첨부가 실제로 없다는 것을
    우리가 확인한 게 아니라, 없다고 회사가 말했다는 사실을 옮길 뿐이다. 원문이 없으면
    선언 여부를 모르므로 False가 아니라 **판정하지 않는다**(호출부가 None으로 저장).
    """
    return any(k in _squeeze(raw_text or "") for k in _NO_ATTACHMENT_DECL)


# 외부 문서 참조(Story 6.4, 2026-08-07). `declares_no_attachment`와 **반대 방향의 사실**이다:
# 저쪽은 "받으러 갈 문서가 없다", 이쪽은 "있다".
#
# ⚠️ 어휘 선정에 규율이 있다 — **변별력을 먼저 쟀다.** 2026-07-28에 `is_unrankable`의 참조
# 검사를 폐기한 이유가 `관련 웹페이지`가 DART 표준 서식 필드라 전건에 있었기 때문이고,
# 그 결과 불투명순 1·2·3등이 전부 오탐이었다. 전 코퍼스 519건 실측:
#     게재 · 게재일시 · 관련 웹페이지   463건  → 서식 필드. **쓰지 않는다**
#     related_url 보유                60건  → 위 필드에서 추출한 값. 같은 이유로 제외
#     첨부된 180 · 첨부파일 45 · 첨부한 5    → 채택
# 그리고 `첨부서류`는 **채택하지 않는다** — 선언 문구 `첨부서류를 생략한`의 부분문자열이라
# 넣으면 선언·참조가 9건 공존한다(실제로는 0건, 라벨링 기준서 §2-F).
_ATTACHMENT_REF = ("첨부된", "첨부파일", "첨부한", "첨부를참조", "첨부참조", "첨부문서")


# 예고(안내공시) — **계획이 아니라 "곧 내겠다"는 알림**(OQ-4 종결 2026-08-07).
#
# ⚠️ 여기서도 변별력을 먼저 쟀고, 또 걸릴 뻔했다. 전 코퍼스 519건에서 `예고(안내공시)`
# 문자열은 **104건**에 있는데 진짜 예고 문서는 **56건**뿐이다. 나머지 48건은 **진짜 계획이
# 자기 예고를 참조**하는 경우다:
#     제목부   우리금융지주/기업가치 제고 계획 예고(안내공시)/(2024.06.24)   ← 이 문서가 예고다
#     관련공시  ※ 관련공시  2024-06-24 기업가치 제고 계획 예고(안내공시)     ← 남의 얘기다
# 단순 포함으로 잡으면 `axis_targets` 40건이 예고로 뒤집힌다 — 목표를 다 공시한 회사가
# "예고만 한 회사"가 되는 것이다. 그래서 **제목 서식**(`…예고(안내공시)/(`)만 인정한다.
# DART 제목줄은 `회사명/보고서명/(YYYY.MM.DD)` 형태라 뒤따르는 `/(`가 제목임을 증명한다.
_NOTICE_TITLE = "예고(안내공시)/("


def is_notice(raw_text: str | None) -> bool:
    """이 문서가 **계획 예고(안내공시)** 자체인가 — 계획 문서가 아니라 알림이다.

    실측 56건(2026-08-07). 전부 `no_targets`이고 전부 첨부 부존재 선언이 없다 —
    당연하다, 아직 낼 것이 없으니까.

    **왜 별도 범주인가.** "본문에 목표가 없다"는 사실은 무언급과 같지만 **이유와 행동이
    다르다**: 예고는 미공시가 아니라 *아직 시점이 안 된 것*이다. 그래서
      · 첨부 워크리스트가 **부르지 않는다**(예고문의 첨부를 받으러 갈 이유가 없다 —
        실측 96건 중 56건이 이것이었다)
      · 화면이 "판정 보류"가 아니라 "계획 예고됨"이라고 말한다
    `exempt_short_form`을 죽이고 `attachment_absent`로 옮겼을 때와 **같은 논리**다:
    사실이 같아도 이유와 행동이 다르면 다른 칸이다.
    """
    return _NOTICE_TITLE in _squeeze(raw_text or "")


def references_external_plan(raw_text: str | None) -> bool:
    """본문이 **첨부 문서를 가리키는가** — 비가독 판정의 단일 정의처.

    `declares_no_attachment`와 마찬가지로 근거는 **회사가 쓴 문장**이다. 첨부가 실제로
    존재하는지 우리가 확인한 게 아니라, 있다고 회사가 말했다는 사실을 옮긴다.

    이 술어의 쓰임은 **게이트가 아니라 라벨**이다(Story 6.4). 순위 대상 여부는 여전히
    `is_unrankable`의 `count==4`가 정하고, 이것은 이미 빠진 종목의 **사유**만 가른다.
    틀렸을 때의 비용이 "화면 1등이 오탐"에서 "배지 문구 하나"로 내려간 것이 2026-07-28에
    폐기한 규칙과의 차이다.
    """
    return any(k in _squeeze(raw_text or "") for k in _ATTACHMENT_REF)


# ── 순위 불가의 사유 — 세 범주 (Story 6.4 / FR-15, 2026-08-07) ──
#
# 리드 결정으로 **누락이 기준축**이 됐다(PRD §1.1). 기준축이 되면 아래 둘은 더 이상 같은
# 칸에 있을 수 없다 — 전자는 **찾던 신호 그 자체**이고 후자는 **우리 파이프라인의 한계**다.
# `attachments/README.md`가 이미 계약으로 갖고 있던 구분을 부축에서 주축으로 올린 것이며,
# 새 개념이 아니다.
#
# **셋인 이유**: 둘로 접으면 근거 없는 67건을 어느 한쪽으로 밀어야 한다. "회사가 안 냈다"와
# "우리가 못 읽었다"가 다른 범주이듯 **"둘 중 어느 쪽인지 모른다"도 다른 범주**다.
# 모르는 것에 이름을 붙이는 순간 그것이 세탁이다(NFR2).
UNDISCLOSED = "undisclosed"  # 미공시 — 회사가 첨부 없이 기재했다고 선언. **신호다**
UNREADABLE = "unreadable"  # 비가독 — 본문 밖(첨부)에 있다. **우리 한계**, 워크리스트로
NOTICE = "notice"  # 예고 — 곧 내겠다는 알림. **아직 시점이 안 된 것**, 워크리스트 제외
UNSTATED = "unstated"  # 무언급 — 어느 근거도 없다. **판정 보류**


# `unrankable_reason`이 읽는 계획 필드. ORM 객체를 그대로 넘기지 않고 이 목록으로 좁혀,
# 판정이 무엇에 의존하는지 호출부에서 보이게 한다(축 5 + 첨부 선언 + 원문).
_REASON_FIELDS = (
    "target_roe",
    "target_payout_ratio",
    "target_total_return_ratio",
    "period_start",
    "buyback_planned",
    "attachment_absent",
    "raw_text",
)


def plan_reason_row(plan: Any) -> dict[str, Any]:
    """ORM 계획 객체 → `unrankable_reason`이 읽는 최소 매핑."""
    return {f: getattr(plan, f, None) for f in _REASON_FIELDS}


def unrankable_reason(plan: Mapping[str, object]) -> str | None:
    """순위 불가라면 그 **사유**, 순위 가능하면 None.

    `is_unrankable`을 **바꾸지 않는다** — 순위 대상 여부는 여전히 `count==4`가 정하고,
    이것은 이미 빠진 종목에 사유 라벨만 붙인다. 2026-07-28에 폐기한 규칙과 재료(참조 문구)는
    같지만 자리가 다르다: 그때는 게이트였고 지금은 라벨이다. 틀렸을 때의 비용이
    "불투명순 1·2·3등이 오탐"에서 "배지 문구 하나"로 내려간다.

    판정 순서에 근거가 있다 — **회사가 직접 쓴 선언이 가장 강한 증거**이므로 먼저 본다.
    선언과 참조가 **공존하는 행은 0건**이고 예고는 셋 어디와도 겹치지 않으므로, 이 순서는
    실제로는 아무것도 가리지 않는다(라벨링 기준서 §2-F — 상상한 경계가 아니라 세어본 결과).

    실측(2026-08-07, 축=0 구간 206건):

        미공시 110 · 비가독 29 · **예고 56** · 무언급 11

    예고는 OQ-4를 닫으면서 **넷째로 추가됐다**(같은 날 오후). 처음 셋으로 갈랐을 때
    무언급이 67건이었는데 **그중 56건이 예고였다** — "판정 보류"라던 통의 84%가 실은
    애매하지 않았고, 우리가 제목을 안 봤을 뿐이다. 남은 무언급 11건이 진짜 모르는 것이다.
    """
    if not is_unrankable(plan):
        return None
    raw = plan.get("raw_text")
    if plan.get("attachment_absent"):
        return UNDISCLOSED
    if references_external_plan(raw):  # type: ignore[arg-type]
        return UNREADABLE
    if is_notice(raw):  # type: ignore[arg-type]
        return NOTICE
    return UNSTATED


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

# 첨부 부존재는 body_signal과 **다른 축**이라 라벨도 따로 둔다. 화면은 둘을 조합해
# 말한다("본문에 목표 없음 · 약식 공시 — 회사가 첨부 없음을 명시").
ATTACHMENT_ABSENT_LABEL = "약식 공시 — 회사가 첨부 없음을 명시"
