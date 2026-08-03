"""DART 밸류업 계획공시 어댑터 — valueup_plan의 writer (AD-3, source="dart").

"기업가치 제고 계획"은 구조화 재무 API가 없는 **자유서식 공시**라 2단계로 수집한다:
  1) list.json(공시검색, JSON)  → report_nm 매칭으로 밸류업 공시 발견(다중·다중페이지)
  2) document.xml(ZIP 바이너리) → 압축 해제·태그 스트립으로 원문 raw_text 확보

정확성 계약의 핵심 = **raw_text 보존 + 멱등 upsert**. 목표 필드(ROE·배당성향·PBR·기간·자사주)는
best-effort 정규식이며 **애매하면 null**(틀린 non-null 값 금지 — 코드리뷰 반영).

설계 규약(코드리뷰 반영):
- **문서별 격리**: 한 문서/후반 페이지 실패가 그 종목의 이미 모은 공시를 날리지 않는다.
- **성공/실패 구분**: 유효 문서를 파싱한 결과만 upsert(권위) → repository가 목표필드를 null 포함
  전체 교체. 문서 fetch 실패(비ZIP·HTTP오류·빈 응답)는 upsert하지 않아 기존 레코드를 보존한다.
- ⚠️ document.xml은 ZIP 바이너리 → dart.py의 `_get`(resp.json) 재사용 금지. `_fetch_document`는
  `resp.content`를 쓰고, 실패는 DartDocumentError로 격리. HTTP 하드닝·키 미노출은 dart.py 재사용.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy.orm import Session
from urllib3.util.retry import Retry

from app.analysis.plan_signals import classify_body
from app.config import settings
from app.ingest.base import SourceAdapter
from app.ingest.dart import (
    _BASE,
    _MIN_INTERVAL,
    _TIMEOUT,
    DartAdapterError,
    _RateLimiter,
)
from app.repositories.valueup_plan import upsert_valueup_plan

# report_nm 매칭(공백 제거 후 부분일치). pblntf_ty로 좁히지 않는다(과대필터 방지).
_REPORT_KEYWORD = "기업가치제고계획"
# 계획이 아닌 공시 제외(1.10, F9 실증): 이행현황(사후보고)·철회는 목표 공시가 아님.
# 정정([기재정정] 등)은 유지 — 최신 정정이 권위 있는 목표(2.1 최신공시 채택 규칙과 정합).
_REPORT_EXCLUDE = ("이행현황", "철회")


def _is_plan_report(report_nm: str | None) -> bool:
    """report_nm이 '계획' 공시인지 판정(공백 제거 부분일치 + 부정 키워드 제외)."""
    compact = str(report_nm or "").replace(" ", "")
    if _REPORT_KEYWORD not in compact:
        return False
    return not any(kw in compact for kw in _REPORT_EXCLUDE)
_MAX_PAGES = 50  # 페이지네이션 상한(과대 total_page 방어)
_MAX_ZIP_BYTES = 20 * 1024 * 1024  # 문서 ZIP 원본 크기 상한
_MAX_MEMBER_BYTES = 10 * 1024 * 1024  # 멤버 압축해제 크기 상한(zip-bomb 방어)
_MAX_TOTAL_BYTES = 50 * 1024 * 1024  # 누적 압축해제 상한(일괄리뷰 Med: 멤버별 한도 우회 방어)
_MAX_MEMBERS = 200  # 텍스트 멤버 수 상한
_TEXT_EXTS = (".xml", ".html", ".htm", ".txt")  # 텍스트 멤버만(바이너리 오탐 방지)
_PBR_MAX = 100.0  # 현실적 PBR 상한(연도·페이지번호 오탐 배제)

# ── best-effort 파싱 패턴 ──
# 값 뒤에 p/P/포(인트)가 오면 '퍼센트포인트'(증감)라 절대목표 아님 → 제외.
#
# **상한 약속 배제**(2026-08-03, P1-5): "이내·이하·미만"이 붙은 값은 목표가 아니라 **상한**이다.
# 대한항공 "당기순이익의 30% **이내** 주주환원", 넷마블 "40% **이내**로 확대"가 실샘플이다.
# 우리 채점은 목표를 "달성해야 할 하한"으로 다루므로, 이 값을 주우면 **회사가 하지 않은
# 약속으로 채점**하게 된다(NFR2 위반). 전 패턴에 일괄 적용한다 — 방향과 무관하게 틀린다.
_CEILING = r"(?!\s*(?:이내|이하|미만))"
_PCT = r"(\d+(?:\.\d+)?)\s*%(?![pP포])" + _CEILING
# ROE 별칭(1.10, 실샘플 6건: '자기자본이익률' 표기).
_ROE_LABEL = r"(?:ROE|자기자본이익률)"
# 경쟁 지표 라벨(일괄리뷰 2026-07-13 High): gap이 다른 지표를 가로질러 그 지표의 %를
# 훔쳐오는 오탐 차단 — 라벨별로 "자신이 아닌" 지표들을 배제한다.
_OTHERS_FOR_ROE = r"배당성향|주주환원|PBR|영업이익|부채비율"
_OTHERS_FOR_PAYOUT = r"ROE|자기자본이익률|주주환원|PBR|영업이익|부채비율"
# 주주환원율 라벨이 자기 자신이므로 배제 목록에서 빼고, 배당성향을 경쟁 지표로 넣는다.
_OTHERS_FOR_RETURN = r"ROE|자기자본이익률|배당성향|PBR|영업이익|부채비율"


def _plain_gap(others: str) -> str:
    """라벨-값 gap: 개행·숫자·%·경쟁 지표 금지 + 괄호 한정어 1개 허용.

    괄호 안은 숫자·백틱 허용(실샘플 `목표(\\`24~\\`30년 평균)`)하되 **%·경쟁 지표는 금지**
    (일괄리뷰 High: `ROE(2024년 5%) 배당성향 30%`가 30을 ROE로 훔치던 오탐 차단).
    """
    pre = rf"(?:(?!{others})[^0-9%\n(]){{0,15}}"
    paren = rf"(?:\((?:(?!%|{others})[^)\n]){{0,25}}\)\s*[:：]?\s*)?"
    tail = rf"(?:(?!{others})[^0-9%\n]){{0,10}}?"
    return pre + paren + tail


_ROE_RE = re.compile(_ROE_LABEL + _plain_gap(_OTHERS_FOR_ROE) + _PCT, re.IGNORECASE)
# '배당성향'만 매칭(주주환원율은 다른 지표라 target_payout_ratio에 넣지 않음).
_PAYOUT_RE = re.compile(r"배당성향" + _plain_gap(_OTHERS_FOR_PAYOUT) + _PCT)
# 총주주환원율(배당+자사주매입)/순이익 — **배당성향과 다른 지표**라 별도 필드로 받는다(5-1).
# 이 구분은 처음부터 의도된 것이었고(위 주석), 빠져 있던 건 받아줄 필드였다.
_RETURN_LABEL = r"(?:총\s*주주환원율|주주환원율|총주주환원)"
# **목표 표지 필수**(5-1 실샘플 검증). 주주환원율은 계획 공시에서 목표만큼이나 자주
# *이행 실적*으로 등장한다 — "'25년 총 주주환원율 268.0%", "총주주환원율 72.8%",
# "3년 평균 주주환원율 78%(현황)". 라벨+숫자만 보면 13건 중 5건이 과거 실적이었다.
# 값 뒤 짧은 구간에 목표를 뜻하는 말이 와야만 채택한다(같은 절 안 — 개행은 넘지 않는다).
# 보수적으로 놓치는 쪽을 택한다: 애매하면 null(NFR2).
# **경쟁 지표 라벨 배제**(교차리뷰 2026-07-23 CONFIRMED): 표지 창이 다른 지표의 목표 표지를
# 훔쳐오는 오탐 차단. `_plain_gap`은 값 앞 gap에서만 경쟁 라벨을 막았고 이 룩어헤드(값 뒤)는
# 막지 않아, "주주환원율 50% ROE 목표 12%"가 ROE의 '목표'를 빌려 50을 총주주환원율 목표로
# 오채택했다(틀린 non-null → NFR2 위반). 표지 앞에 경쟁 라벨이 끼면 매칭을 끊는다.
_TARGET_MARK = (
    rf"(?=(?:(?!{_OTHERS_FOR_RETURN})[^\n]){{0,12}}?(?:목표|지향|이상|확대|원칙|수준|계획))"
)
_RETURN_RE = re.compile(
    _RETURN_LABEL + _plain_gap(_OTHERS_FOR_RETURN) + _PCT + _TARGET_MARK
)

# ── [P1-2, 2026-07-31] 범위 표현: "ROE 11~13%" ──
#
# `_plain_gap`은 라벨-값 사이에 숫자를 허용하지 않으므로(경쟁 지표의 %를 훔치는 오탐 차단)
# 범위의 **앞 숫자에서 매칭이 끊겨** 통째로 버려졌다. 실측: ROE 24건 중 22건, 주주환원율
# 8건 전부, 배당성향 6건 중 5건 — 합계 35건이 그냥 사라지고 있었다.
# 삼성화재 "ROE 11~13%", "2030년까지 연결 ROE 13~15%"처럼 **명확한 공시**들이다.
#
# **하한을 채택한다**(리드 결정, 2026-07-31). 범위로 약속했다면 회사가 확실히 약속한 것은
# 하한이고, 중앙값은 공시에 없는 숫자를 우리가 만드는 것이다("억지 추정 금지", SM-C1).
# 대신 **범위였다는 사실을 함께 남긴다**(target_ranges) — 하한만 보면 달성 판정이
# 관대해지므로, 화면이 원문 범위를 말할 수 있어야 한다.
_PCT_RANGE = r"(\d+(?:\.\d+)?)\s*[~∼\-–]\s*(\d+(?:\.\d+)?)\s*%(?![pP포])" + _CEILING
_ROE_RANGE_RE = re.compile(
    _ROE_LABEL + _plain_gap(_OTHERS_FOR_ROE) + _PCT_RANGE, re.IGNORECASE
)
_PAYOUT_RANGE_RE = re.compile(r"배당성향" + _plain_gap(_OTHERS_FOR_PAYOUT) + _PCT_RANGE)
_RETURN_RANGE_RE = re.compile(
    _RETURN_LABEL + _plain_gap(_OTHERS_FOR_RETURN) + _PCT_RANGE + _TARGET_MARK
)


# ── [P1-5, 2026-08-03] 못 읽던 두 형태 ──
#
# P1-5는 "우리 4축 밖의 지표로 공시한 기업" 문제로 기록돼 있었으나, 유니버스 확대 후
# other_metric 22건의 원문을 읽으니 **절반 가까이가 배당성향·주주환원율**이었다 — 축은
# 이미 갖고 있고 파서가 못 읽었을 뿐이다. 두 계열로 갈린다.
#
# 계열A — **역순(값 → 라벨)**: "당기순이익의 40%이상의 배당성향"(동방아그로·에스엘·
#   텔코웨어·한국앤컴퍼니). 기존 패턴은 전부 라벨→값 방향뿐이었다.
# 계열B — **라벨과 값 사이에 연도/평균 수식어**: "ROE : '26년까지 7%"(금호석유화학),
#   "ROE 3년 평균 20%"(JW중외제약), "주주환원율 3년 평균 60%"(에프앤에프홀딩스).
#   `_plain_gap`이 숫자를 막아 끊긴다 — P1-2 범위 버그와 같은 뿌리다.

# 계열B의 수식어. **수치가 텍스트에 있는 것만** 인정한다(SM-C1: 억지 추정 금지).
_QUALIFIER = (
    r"(?:\d{1,2}\s*개?년\s*(?:평균|연평균)|CAGR"
    r"|[`'‘’]?\d{2,4}\s*년\s*까지"
    r"|[`'‘’]?\d{2}\s*[~\-–∼]\s*[`'‘’]?\d{2}\s*년"
    r"|[`'‘’]?\d{2,4}\s*년(?:도)?에?)"
)


def _qualified_gap(others: str) -> str:
    """라벨 → (연도/평균 수식어) → 값. 수식어 **말고는** 숫자를 허용하지 않는다.

    `_plain_gap`을 그대로 열면 경쟁 지표의 %를 훔치므로, 열어주는 것은 수식어 토큰
    하나뿐이다. 수식어 자체가 목표인지 실적인지는 정규식이 판정하지 못하므로
    `_forward_qualifier`가 공시연도와 대조해 뒤에서 거른다.
    """
    head = rf"(?:(?!{others})[^0-9%\n(]){{0,12}}"
    tail = rf"(?:(?!{others})[^0-9%\n]){{0,8}}?"
    return head + rf"({_QUALIFIER})" + tail


_ROE_QUAL_RE = re.compile(
    _ROE_LABEL + _qualified_gap(_OTHERS_FOR_ROE) + _PCT, re.IGNORECASE
)
_PAYOUT_QUAL_RE = re.compile(r"배당성향" + _qualified_gap(_OTHERS_FOR_PAYOUT) + _PCT)
# 주주환원율은 목표만큼이나 자주 '이행 실적'으로 등장하므로 기존 목표 표지 가드를 유지한다.
_RETURN_QUAL_RE = re.compile(
    _RETURN_LABEL + _qualified_gap(_OTHERS_FOR_RETURN) + _PCT + _TARGET_MARK
)

# 계열A — 역순은 **배당성향만** 연다. 주주환원율은 역순 탐침에서 57건이 걸렸는데 대부분
# 오탐이었다(포스코홀딩스 `ROIC 6~9%`, KB금융 `CET1 13.5%`를 환원율 목표로 훔쳤다).
# 배당성향은 "순이익의 N%" 관용구가 굳어 있어 역순이 안전한 유일한 축이다.
_PAYOUT_REVERSE_RE = re.compile(
    _PCT + rf"(?:(?!{_OTHERS_FOR_PAYOUT})[^0-9%\n]){{0,25}}?(?:의\s*)?배당성향"
)
# 역방향 gap은 **값 뒤**만 막는다 — 값 **앞**에 붙은 남의 라벨은 정규식이 못 본다.
# "부채비율 : 100% 이하 - 배당성향" 같은 배치에서 100을 훔치는 경로(2026-07-23 교차리뷰
# ③과 같은 계열)라, 매칭 후 값 앞 창을 파이썬에서 다시 검사한다.
_PAYOUT_OTHERS_RE = re.compile(_OTHERS_FOR_PAYOUT)
_REVERSE_LOOKBACK = 20


def _forward_qualifier(qualifier: str, disclosure_year: int | None) -> bool:
    """이 수식어가 **미래를 가리키는가** — 실적을 목표로 오채택하지 않기 위한 판정.

    "3년 평균"·"CAGR"·"2028년까지"는 그 자체로 전망이다. 그러나 맨 연도("2024년 ROE 5%")는
    실적일 수 있다 — 이때는 **공시연도보다 뒤인 연도만** 목표로 본다. 없는 값을 짓는 게
    아니라 문서가 이미 가진 두 날짜를 비교하는 것이다. 공시연도를 모르면 채택하지 않는다.
    """
    if re.search(r"평균|연평균|CAGR|까지", qualifier):
        return True
    years = re.findall(r"\d{2,4}", qualifier)
    if not years or disclosure_year is None:
        return False
    # 범위('24~'26년)는 종료연도 기준 — 그 해까지 가겠다는 약속이다.
    return _expand_year(years[-1], disclosure_year) > disclosure_year


def _arrow_tail(others: str) -> str:
    """"현재 X% → 목표 Y%" 화살표 체인(우변 채택). 좌변 gap은 숫자 허용(연도 서술 통과)
    하되 **경쟁 지표 라벨은 금지**(일괄리뷰 High: 남의 화살표를 훔치던 오탐 차단), 개행 금지."""
    seg_l = rf"(?:(?!{others})[^%\n]){{0,30}}?"
    seg_m = rf"(?:(?!{others})[^\n%]){{0,25}}?"
    return (
        seg_l + r"(\d+(?:\.\d+)?)\s*%"
        + seg_m + r"(?:→|⇒|➔)\s*" + seg_m + r"(\d+(?:\.\d+)?)\s*%(?![pP포])"
    )


_ROE_ARROW_RE = re.compile(_ROE_LABEL + _arrow_tail(_OTHERS_FOR_ROE), re.IGNORECASE)
_PAYOUT_ARROW_RE = re.compile(r"배당성향" + _arrow_tail(_OTHERS_FOR_PAYOUT))
_RETURN_ARROW_RE = re.compile(_RETURN_LABEL + _arrow_tail(_OTHERS_FOR_RETURN) + _TARGET_MARK)
# PBR은 '배' 단위 **필수**(연도·페이지번호를 PBR로 오탐하는 것 차단).
_PBR_RE = re.compile(r"PBR[^0-9\n]{0,15}?(\d+(?:\.\d+)?)\s*배", re.IGNORECASE)
_PERIOD_RE = re.compile(r"(20\d{2})\s*년?\s*[~\-–∼]\s*(20\d{2})")
# 1.10: 백틱/따옴표 표식이 붙은 2자리 연도 범위(실샘플 `24~`30년) → 20xx 확장.
# 표식·'년' 필수(24~26개월 같은 비연도 오탐 방지).
_PERIOD2_RE = re.compile(r"[`'‘’]\s*(\d{2})\s*[~\-–∼]\s*[`'‘’]?\s*(\d{2})\s*년")
# 기간 후보 선택 앵커(일괄리뷰 Med: 과거 비교기간을 계획기간으로 오인 방지).
# '기간'은 제외 — "비교기간"에도 들어가 과거 범위를 앵커시키는 역효과.
_PERIOD_CTX_RE = re.compile(r"(계획|목표|향후|중장기)")

# [P1-8, 2026-07-31] 기간 표현 확장. 실측(실패 212건에서 표현을 센 결과):
#   중장기(수치없음) 71 · YYYY년까지 24 · 지속/매년 20 · 'YY년까지 15 · N개년 13 ·
#   향후 N년 12 · 표현 자체가 없음 94
# 넓히는 것은 **수치가 텍스트에 있는 것뿐**이다. "중장기"·"지속적으로"처럼 수치화할 수 없는
# 표현은 억지 추정하지 않고 미상으로 남긴다(SM-C1) — 커버리지보다 정확도 우선(NFR2).
#
# "YYYY년부터 YYYY년까지" / "'23회계연도부터 '25회계연도까지" — 시작·종료가 둘 다 있다.
_PERIOD_FROM_TO_RE = re.compile(
    r"[`'‘’]?(\d{2}|20\d{2})\s*(?:회계연도|년|년도)?\s*부터\s*"
    r"[`'‘’]?(\d{2}|20\d{2})\s*(?:회계연도|년|년도)?\s*까지"
)
# "2030년까지" / "'28년까지" — **종료연도만** 명시. 시작은 공시일로 본다(아래 주석 참조).
_PERIOD_UNTIL_RE = re.compile(r"[`'‘’]?(\d{2}|20\d{2})\s*년\s*까지")
# "향후 3개년" / "향후 3년" — 공시 시점 기준 상대 기간.
_PERIOD_FORWARD_RE = re.compile(r"향후\s*(\d{1,2})\s*개?년")
# "…까지" 전용 앵커. 범위 표기(_PERIOD_CTX_RE, 창 20)보다 넓다 — 실측상 이 형태는
# "주주환원 지속 - 2030년까지 배당성향 30%"처럼 서술이 앞에 길게 붙어 창 20을 벗어난다.
# 창을 넓히고 키워드를 늘려 14건을 더 회수했다(앵커를 아예 없애면 17건이지만, 시장 전망
# 같은 무관한 미래 연도를 주울 위험이 커져 채택하지 않았다).
_PERIOD_UNTIL_CTX_RE = re.compile(r"(계획|목표|향후|중장기|환원|달성|유지|개선|제고)")
_PERIOD_UNTIL_CTX_WINDOW = 60

_PERIOD_MAX_SPAN = 20  # 계획 기간 상한(년). 넘으면 기간이 아니라 오탐으로 본다.


def _expand_year(raw: str, disclosure_year: int | None) -> int | None:
    """'28 → 2028, 2030 → 2030. 2자리는 세기를 공시연도 기준으로 정한다."""
    n = int(raw)
    if len(raw) == 4:
        return n
    base = (disclosure_year or 2000) // 100 * 100
    return base + n


def _select_period(
    text: str, disclosure_year: int | None = None
) -> tuple[str | None, str | None]:
    """문서 내 모든 연도범위 후보 중 계획 문맥에 앵커된 것을 선택(일괄리뷰 Med).

    규칙: (1) 후보 직전 20자에 계획·목표·향후·중장기가 있으면 그 첫 후보,
    (2) 앵커 없고 후보가 전부 같은 범위면 그 값(단일 후보 포함 — 기존 recall 유지),
    (3) 앵커 없이 상이한 범위 다수면 애매 → null(NFR2).

    ■ [P1-8, 2026-07-31] 범위 표기가 없을 때의 확장
        실측상 기간 파싱 실패의 큰 덩어리는 "범위"가 아니라 **종료 시점만** 쓰는 형태였다
        ("2030년까지 배당성향 30%", "'28년까지 …"). 39건이 여기 해당한다.

        이때 **시작을 공시일로 본다**(리드 결정 A, 2026-07-31). 없는 값을 지어내는 것이
        아니라 공시 행위 자체가 약속의 시작점을 정의하기 때문이다 — 2026-03-20에
        "2030년까지 하겠다"고 밝혔다면 그 약속의 구간은 공시일~2030이다.
        `progress_rate`가 재려는 것("약속한 기간 중 얼마나 지났나")과도 정확히 맞는다.

        "향후 3개년"도 같은 성질이다(공시 시점 기준 상대 표현) → 공시연도~공시연도+2.

        **넓히지 않는 것**: "중장기"(71건)·"지속적으로/매년"(20건)처럼 수치가 없는 표현.
        추정하지 않고 미상으로 남긴다.

    범위 표기(기존 규칙)가 하나라도 잡히면 그쪽이 우선한다 — 명시된 범위가 더 강한 근거다.
    """
    cands: list[tuple[int, str, str]] = []
    for m in _PERIOD_RE.finditer(text):
        if int(m.group(1)) <= int(m.group(2)):
            cands.append((m.start(), m.group(1), m.group(2)))
    for m in _PERIOD2_RE.finditer(text):
        start, end = f"20{m.group(1)}", f"20{m.group(2)}"
        if int(start) <= int(end):
            cands.append((m.start(), start, end))
    # "…부터 …까지" — 범위가 명시된 또 하나의 형태(회계연도 표기 포함)
    for m in _PERIOD_FROM_TO_RE.finditer(text):
        s = _expand_year(m.group(1), disclosure_year)
        e = _expand_year(m.group(2), disclosure_year)
        if s is not None and e is not None and s <= e <= s + _PERIOD_MAX_SPAN:
            cands.append((m.start(), str(s), str(e)))
    if cands:
        cands.sort()
        anchored = [
            c for c in cands
            if _PERIOD_CTX_RE.search(text[max(0, c[0] - 20): c[0]])
        ]
        if anchored:
            return anchored[0][1], anchored[0][2]
        if len({(s, e) for _, s, e in cands}) == 1:
            return cands[0][1], cands[0][2]
        return None, None

    # ── 범위 표기가 없을 때: 공시일을 시작으로 보는 확장 ──
    if disclosure_year is None:
        return None, None  # 기준점이 없으면 추정하지 않는다

    # "향후 N개년" — N년간이므로 종료는 시작 + (N-1)
    fm = _PERIOD_FORWARD_RE.search(text)
    if fm:
        n = int(fm.group(1))
        if 1 <= n <= _PERIOD_MAX_SPAN:
            return str(disclosure_year), str(disclosure_year + n - 1)

    # "YYYY년까지" / "'YY년까지" — 종료연도만. 계획 문맥에 앵커된 것만 채택하고,
    # 여러 종료연도가 상충하면 애매로 버린다(기존 규칙과 같은 보수성).
    ends: list[int] = []
    for m in _PERIOD_UNTIL_RE.finditer(text):
        window = text[max(0, m.start() - _PERIOD_UNTIL_CTX_WINDOW): m.start()]
        if not _PERIOD_UNTIL_CTX_RE.search(window):
            continue
        y = _expand_year(m.group(1), disclosure_year)
        # 공시연도 이전이거나 지나치게 먼 미래는 계획 기간이 아니다(과거 실적·비교 문맥)
        if y is not None and disclosure_year <= y <= disclosure_year + _PERIOD_MAX_SPAN:
            ends.append(y)
    if ends and len(set(ends)) == 1:
        return str(disclosure_year), str(ends[0])
    return None, None
_BUYBACK_RE = re.compile(r"(자기주식|자사주)[^\n]{0,15}?(취득|매입|소각)")
# 부정·과거(계획 아님) 문맥 → False 판정.
_BUYBACK_NEG_RE = re.compile(r"(없음|없이|아니|않|미실시|미계획|계획\s*없|완료|기실시)")


class DartDocumentError(DartAdapterError):
    """문서(document.xml) 다운로드/해제 실패 — 종목 전체가 아니라 그 문서만 격리."""


def _safe_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_date(yyyymmdd: str | None) -> str | None:
    """YYYYMMDD → ISO YYYY-MM-DD. strptime으로 엄격 검증, 무효면 None(적재 제외용)."""
    s = (yyyymmdd or "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _strip_tags(s: str) -> str:
    """DART 전용 XML 마크업 태그 제거. 태그 자리를 **개행으로 치환**해 셀/문단 경계를 보존한다
    (라벨과 인접 지표 값이 한 줄로 뭉쳐 오탐되는 것 방지)."""
    text = re.sub(r"<[^>]+>", "\n", s)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)  # 공백류만 축약(개행은 유지)
    text = re.sub(r"\n[ \t]*", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _zip_to_text(content: bytes) -> str:
    """document.xml ZIP → 평문. 비ZIP/빈/추출실패는 DartDocumentError(성공값과 구분).

    텍스트 멤버(.xml/.html/.txt)만, 사이즈 상한으로 읽는다(바이너리 오탐·zip-bomb 방어).
    """
    if not content:
        raise DartDocumentError("빈 문서 응답")
    if len(content) > _MAX_ZIP_BYTES:
        raise DartDocumentError("문서 ZIP 크기 상한 초과")
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        # 비ZIP = DART 오류 HTML/XML 응답 → 실패로 격리(빈 원문으로 오인 금지)
        raise DartDocumentError("ZIP 아님(오류 응답 가능)") from None
    parts: list[str] = []
    total_bytes = 0
    members = 0
    with zf:
        for info in zf.infolist():
            if not info.filename.lower().endswith(_TEXT_EXTS):
                continue
            if info.file_size > _MAX_MEMBER_BYTES:
                continue
            members += 1
            total_bytes += info.file_size
            if members > _MAX_MEMBERS or total_bytes > _MAX_TOTAL_BYTES:
                raise DartDocumentError("문서 누적 압축해제 상한 초과(멤버 수/총 크기)")
            parts.append(_decode(zf.read(info)))
    text = _strip_tags("\n".join(parts))
    if not text:
        raise DartDocumentError("문서에서 텍스트 추출 실패")
    return text


def parse_targets(
    raw_text: str | None, disclosure_date: str | None = None
) -> dict[str, Any]:
    """유효 문서 원문에서 목표 필드 best-effort 추출. 못 찾으면 해당 필드 None.

    보수적: 애매하면 null(틀린 non-null 값 금지). 값 뒤 p(포인트)·단위없는 PBR·범위이상·부정 자사주 배제.

    disclosure_date(ISO)는 기간 파싱에만 쓴다 — "2030년까지"처럼 종료만 밝힌 공시에서
    시작점을 정하는 기준이다(P1-8). 없으면 그 확장 규칙은 적용하지 않는다.
    """
    text = raw_text or ""

    def _num(rx: re.Pattern[str]) -> float | None:
        m = rx.search(text)
        return float(m.group(1)) if m else None

    def _num_with_arrow(arrow_rx: re.Pattern[str], plain_rx: re.Pattern[str]) -> float | None:
        """화살표 체인(현재→목표)은 우변(목표) 채택 — 단 **문서 내 위치가 앞선 쪽 우선**
        (일괄리뷰 Med: 앞의 명시 목표가 뒤쪽 과거실적 표의 화살표에 밀리지 않게).
        같은 위치(같은 clause)에서 화살표가 있으면 화살표 우변이 목표."""
        am = arrow_rx.search(text)
        pm = plain_rx.search(text)
        if am is not None and (pm is None or am.start() <= pm.start()):
            return float(am.group(2))
        return float(pm.group(1)) if pm else None

    pbr = _num(_PBR_RE)
    if pbr is not None and not (0 < pbr <= _PBR_MAX):
        pbr = None  # 연도·비현실적 값 배제

    # 기간: 전체 후보 중 계획 문맥 앵커 우선(일괄리뷰 Med — 과거 비교기간 오인 방지)
    disclosure_year: int | None = None
    if disclosure_date and len(disclosure_date) >= 4 and disclosure_date[:4].isdigit():
        disclosure_year = int(disclosure_date[:4])
    period_start, period_end = _select_period(text, disclosure_year)

    buyback: bool | None = None
    bm = _BUYBACK_RE.search(text)
    if bm:
        window = text[max(0, bm.start() - 10) : bm.end() + 15]
        buyback = False if _BUYBACK_NEG_RE.search(window) else True

    # 범위 표현(P1-2): 기존 규칙이 값을 못 찾았을 때만 하한을 채택한다.
    # 단일 값이 잡혔으면 그쪽이 더 강한 근거이므로 건드리지 않는다.
    ranges: list[str] = []

    def _with_range(plain: float | None, range_rx: re.Pattern[str], key: str) -> float | None:
        if plain is not None:
            return plain
        m = range_rx.search(text)
        if m is None:
            return None
        low, high = float(m.group(1)), float(m.group(2))
        if low > high:  # "13~11%" 같은 역순은 파싱 오류로 보고 채택하지 않는다
            return None
        ranges.append(f"{key}:{m.group(1)}~{m.group(2)}")
        return low

    # [P1-5] 아래 두 폴백은 **기존 규칙이 못 찾았을 때만** 돈다(범위 폴백과 같은 정책).
    # 기존 non-null을 절대 바꾸지 않으므로 회귀 위험이 구조적으로 0이다.
    def _num_qualified(rx: re.Pattern[str]) -> float | None:
        """계열B — 연도/평균 수식어가 낀 형태. 수식어가 미래를 가리킬 때만 채택."""
        for m in rx.finditer(text):
            if _forward_qualifier(m.group(1), disclosure_year):
                return float(m.group(2))
        return None

    def _num_reverse(rx: re.Pattern[str], others_rx: re.Pattern[str]) -> float | None:
        """계열A — 역순(값→라벨). 값 **앞**에 경쟁 지표 라벨이 있으면 그 값은 남의 것이다."""
        for m in rx.finditer(text):
            before = text[max(0, m.start() - _REVERSE_LOOKBACK) : m.start()]
            if others_rx.search(before):
                continue
            return float(m.group(1))
        return None

    roe = _with_range(_num_with_arrow(_ROE_ARROW_RE, _ROE_RE), _ROE_RANGE_RE, "roe")
    if roe is None:
        roe = _num_qualified(_ROE_QUAL_RE)
    payout = _with_range(
        _num_with_arrow(_PAYOUT_ARROW_RE, _PAYOUT_RE), _PAYOUT_RANGE_RE, "payout_ratio"
    )
    if payout is None:
        payout = _num_qualified(_PAYOUT_QUAL_RE)
    if payout is None:
        payout = _num_reverse(_PAYOUT_REVERSE_RE, _PAYOUT_OTHERS_RE)
    total_return = _with_range(
        _num_with_arrow(_RETURN_ARROW_RE, _RETURN_RE),
        _RETURN_RANGE_RE, "total_return_ratio",
    )
    if total_return is None:
        total_return = _num_qualified(_RETURN_QUAL_RE)

    return {
        "target_roe": roe,
        "target_payout_ratio": payout,
        "target_total_return_ratio": total_return,
        "target_pbr": pbr,
        "period_start": period_start,
        "period_end": period_end,
        "buyback_planned": buyback,
        # 하한을 채택한 축과 그 원문 범위 — 하한만 보면 달성 판정이 관대해지므로
        # 화면이 "공시 원문 11~13%"를 말할 수 있어야 한다(값에는 출처가 따라붙는다).
        "target_ranges": ",".join(ranges) if ranges else None,
    }


class DartValueupAdapter(SourceAdapter):
    source = "dart"

    def __init__(self) -> None:
        self._session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._limiter = _RateLimiter(_MIN_INTERVAL)

    # ── fetch (라이브, 키 필요) ──
    def fetch(self, corp_code: str, bgn_de: str, end_de: str) -> dict[str, Any]:
        key = settings.dart_api_key.get_secret_value()
        if not key:
            raise DartAdapterError(
                "DART_API_KEY가 설정되지 않았습니다. .env에 DART_API_KEY를 넣으세요."
            )
        plans: list[dict[str, Any]] = []
        failed: list[tuple[str | None, str]] = []
        page_no = 1
        while page_no <= _MAX_PAGES:
            try:
                data = self._get_json(
                    "list.json",
                    {
                        "crtfc_key": key,
                        "corp_code": corp_code,
                        "bgn_de": bgn_de,
                        "end_de": end_de,
                        "page_no": page_no,
                        "page_count": 100,
                    },
                    allow_no_data=True,
                )
            except DartAdapterError as e:
                # 후반 페이지 실패 시 이미 모은 plan은 보존하고 중단(부분결과 보존)
                failed.append((f"list.json#p{page_no}", type(e).__name__))
                break
            page_items = data.get("list")
            if page_items is None:
                page_items = []
            if not isinstance(page_items, list):  # 형태 이탈 → 페이지 실패로 격리
                failed.append((f"list.json#p{page_no}", "list 형태 오류"))
                break
            for item in page_items:
                if not isinstance(item, Mapping):  # malformed 항목 격리(일괄리뷰 High)
                    continue
                report_nm = str(item.get("report_nm") or "")
                if not _is_plan_report(report_nm):  # 1.10: 이행현황·철회 제외(F9)
                    continue
                disclosure_date = _parse_date(item.get("rcept_dt"))
                rcept_no = item.get("rcept_no")
                if disclosure_date is None:
                    failed.append((rcept_no, "무효 rcept_dt"))
                    continue
                if not rcept_no:
                    failed.append((None, "rcept_no 없음"))
                    continue
                try:
                    raw_text = self._fetch_document(key, rcept_no)  # 문서별 격리
                except DartDocumentError as e:
                    failed.append((rcept_no, type(e).__name__))
                    continue
                plans.append(
                    {
                        "disclosure_date": disclosure_date,
                        "report_nm": report_nm,
                        "raw_text": raw_text,
                        # 출처 추적(0015): 여기까지 이미 손에 쥔 값인데 예전엔 document.xml
                        # 호출에만 쓰고 버렸다 — 그래서 "어느 공시에서 나온 목표인가"를
                        # DB만 보고는 알 수 없었고, 첨부 목록 URL도 조립할 수 없었다.
                        "rcept_no": str(rcept_no),
                    }
                )
            total_page = _safe_int(data.get("total_page"), 1)
            if page_no >= total_page:
                break
            page_no += 1
        return {"corp_code": corp_code, "plans": plans, "failed": failed}

    def _get_json(
        self, endpoint: str, params: Mapping[str, Any], allow_no_data: bool = False
    ) -> dict[str, Any]:
        """list.json 등 JSON 엔드포인트. dart.py `_get`과 동일한 status 처리. 키 미노출."""
        self._limiter.acquire()
        try:
            resp = self._session.get(
                f"{_BASE}/{endpoint}", params=params, timeout=_TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            # ValueError=비JSON 200(dart.py `_get`과 동일 처리, 일괄리뷰 High)
            raise DartAdapterError(
                f"DART 요청 실패: endpoint={endpoint} ({type(e).__name__})"
            ) from None
        if not isinstance(data, dict):
            # 비-dict JSON(list/str)이 AttributeError로 누출되면 페이지 격리 계약이
            # 깨진다(DartAdapterError만 부분결과 보존 경로를 탄다, 일괄리뷰 High)
            raise DartAdapterError(f"DART 응답 형태 오류: endpoint={endpoint}")
        status = data.get("status")
        if status == "000":
            return data
        if allow_no_data and status == "013":  # 조회된 데이터 없음
            return {"list": []}
        raise DartAdapterError(
            f"DART API 오류: endpoint={endpoint}, status={status}, "
            f"msg={data.get('message')}"
        )

    def _fetch_document(self, key: str, rcept_no: str) -> str:
        """document.xml(ZIP 바이너리) 다운로드 → 평문. 실패는 DartDocumentError로 격리."""
        self._limiter.acquire()
        try:
            resp = self._session.get(
                f"{_BASE}/document.xml",
                params={"crtfc_key": key, "rcept_no": rcept_no},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.content  # 바이너리(ZIP) — resp.json 금지
        except requests.RequestException as e:
            raise DartDocumentError(
                f"문서 다운로드 실패 ({type(e).__name__})"
            ) from None
        return _zip_to_text(content)  # 비ZIP/빈/추출실패 → DartDocumentError

    # ── normalize (순수, 테스트 가능) ──
    def normalize(self, raw: Mapping[str, Any]) -> list[dict[str, Any]]:
        corp_code = raw["corp_code"]
        recs: list[dict[str, Any]] = []
        for plan in raw.get("plans", []):
            rec: dict[str, Any] = {
                "corp_code": corp_code,
                "disclosure_date": plan["disclosure_date"],
                "raw_text": plan.get("raw_text"),
                "rcept_no": plan.get("rcept_no"),  # 출처 추적(0015)
            }
            # 공시일을 함께 넘긴다 — "2030년까지"처럼 종료만 밝힌 공시의 시작점 기준(P1-8)
            rec.update(parse_targets(plan.get("raw_text"), plan["disclosure_date"]))
            # 본문 신호(0018): 축을 못 채웠을 때 **왜**인지를 수집 시점에 함께 굳힌다.
            # 원문이 여기 있을 때 판정해야 서빙이 raw_text를 다시 읽지 않는다.
            signal = classify_body(plan.get("raw_text"), rec)
            rec["body_signal"] = signal.kind
            rec["body_reference_date"] = signal.referenced_date
            recs.append(rec)
        return recs

    # ── upsert (멱등, 유효 문서 기반 전체 교체) ──
    def upsert(self, session: Session, records: Sequence[dict[str, Any]]) -> int:
        for rec in records:
            upsert_valueup_plan(session, rec)
        session.flush()
        return len(records)
