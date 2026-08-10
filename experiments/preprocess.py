"""공시 본문 전처리 — 스타일시트 제거 + 절 단위 분할.

두 가지를 한다. 둘 다 2026-08-06 실측이 시킨 일이다.

■ 1. DART XForms 스타일시트 제거
    `valueup_plan.raw_text`는 뷰어의 CSS가 본문 앞에 통째로 붙어 있다. 실측: 원문 평균
    2,039자 중 **본문은 991자(중앙값 비율 48.7%)**. 나머지 절반은 `.xforms td { padding
    -left:0px; ... }` 같은 규칙이다. 인코더에 그대로 넣으면 512 토큰 예산의 절반을
    스타일시트가 먹는다.

    제거는 **문서 앞머리의 CSS 규칙 블록만** 벗긴다. `text.rfind("}")`로 자르는 방식은
    본문에 중괄호가 하나라도 있으면 본문을 통째로 날린다 — 그래서 쓰지 않는다. 대신
    선두에서부터 `선택자 { 선언부 }` 한 덩어리씩 확인하며 **선택자가 CSS로 보일 때만**
    벗기고, 아니면 즉시 멈춘다. 본문은 절대 건드리지 않는다(선언부에 한글이 있어도 —
    `font-family: 돋움체` — 판정은 선택자로만 한다).

■ 2. 절(section) 단위 분할
    빈 줄 기준 분할은 **전 문서가 문단 1개**로 나온다(실측 p50=p90=max=1). 본문이 한
    덩어리 문자열이기 때문이다. 대신 공시 서식의 번호 절이 실제 경계다:

        …(머리말)… 1. 계획서 명칭 … 2. 주요 내용 … 3. 조세특례제한법 … 4. 결정일자 …

    판정 신호는 절 하나에 갇혀 있다 — `旣공시(2026.2.6) 내용 참조`도 `첨부 없이`도
    항상 `2. 주요 내용`이다. 그래서 이것이 MIL의 bag 단위이고, attention이 고른 절이
    그대로 "근거 한 줄"이 된다.

    번호 오탐(`2026.03.23`, `제104조의27`)은 두 겹으로 막는다: 앞 글자가 숫자·점이면
    제외하고, 남은 후보 중 **1부터 단조 증가하는 것만** 절로 인정한다. 서식이 아닌
    문서는 절이 안 잡히므로 문장 분할로 폴백한다(빈 bag은 만들지 않는다).

실행(코퍼스 전체 검증):
    .venv\\Scripts\\python.exe experiments\\preprocess.py
"""
from __future__ import annotations

import re
import sqlite3
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis.plan_signals import is_notice as _prod_is_notice  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# ── 1. 스타일시트 제거 ──────────────────────────────────────────────────────

# 한 덩어리: 선택자 + { 선언부 }. 중첩 중괄호는 CSS 규칙에 없으므로 [^{}]로 충분하다.
_RULE = re.compile(r"\s*(?P<sel>[^{}]*?)\{(?P<decls>[^{}]*)\}")
# CSS 선택자로 인정하는 문자만. 한글이 들어오면 본문이므로 여기서 탈락한다.
_SELECTOR_OK = re.compile(r"^[.#*a-zA-Z0-9_\-\s:,>+~\[\]=\"'()]+$")
_HANGUL = re.compile(r"[가-힣]")


def _looks_like_selector(sel: str) -> bool:
    s = sel.strip()
    if not s or _HANGUL.search(s):
        return False
    if not _SELECTOR_OK.match(s):
        return False
    # 최소 조건: 클래스/아이디/와일드카드/태그명으로 시작한다.
    return bool(re.match(r"^[.#*a-zA-Z]", s))


def strip_stylesheet(text: str) -> str:
    """앞머리의 CSS 규칙 블록만 벗긴다. CSS가 없으면 원문 그대로 반환."""
    pos = 0
    while True:
        m = _RULE.match(text, pos)
        if not m or not _looks_like_selector(m.group("sel")):
            break
        pos = m.end()
    return text[pos:]


_WS = re.compile(r"[ \t ]+")


def clean(text: str | None) -> str:
    """스타일시트 제거 + 공백 정규화. 글자는 지우지 않는다(신호 문장 보존이 계약)."""
    t = strip_stylesheet(text or "")
    t = t.replace("\r", "\n")
    t = _WS.sub(" ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    return t.strip()


# ── 2. 절 분할 ──────────────────────────────────────────────────────────────

# 앞 글자가 숫자·점이면 번호가 아니다(2026.03.23 / 제104조의27 차단).
_SECTION_CAND = re.compile(r"(?<![0-9.])(?<![0-9] )\b(\d{1,2})\.\s*([가-힣]{1,12})")
_SENT = re.compile(r"(?<=[다음임])\.\s+|(?<=니다)\.\s*")

# 최상위 절의 머리말 — 전 코퍼스 실측(2026-08-06)으로 뽑았다. **성장 중 목록이다**:
# 서식이 바뀌면 새 머리말이 나타나고, 그때는 폴백(문장 분할)으로 내려간다.
#
# 번호만으로 자르면 안 되는 이유: 계획 본문이 `2. 주요 내용` **안에서 다시 1부터** 번호를
# 매긴다(SK하이닉스: 1.기업 개요 2.현황 진단 3.목표 설정 4.계획 수립). 단조 증가 규칙만
# 쓰면 이 중첩 목차가 최상위 절로 승격돼 bag 경계가 본문 한가운데를 가른다.
_TOP_HEADERS = ("계획서", "주요", "조세특례제한법", "결정일자", "관련", "기타", "상기")


def _section_marks(text: str) -> list[tuple[int, int]]:
    """(시작위치, 절번호) — 최상위 머리말이면서 번호가 증가하는 후보만 절로 인정한다."""
    marks: list[tuple[int, int]] = []
    last = 0
    for m in _SECTION_CAND.finditer(text):
        n = int(m.group(1))
        head = m.group(2)
        if n > last and head.startswith(_TOP_HEADERS):
            marks.append((m.start(), n))
            last = n
    return marks


def segments(text: str | None, *, min_len: int = 10) -> list[tuple[str, str]]:
    """문서를 bag으로 — [(라벨, 본문), ...]. 빈 리스트는 반환하지 않는다.

    라벨은 `header` 또는 절 번호(`1`, `2`, …), 폴백일 때는 `s1`, `s2`, ….
    머리말도 bag에 넣는다 — 공시 제목에 신호가 실린다("…고배당기업 표시를 위한 재공시").
    """
    t = clean(text)
    if not t:
        return []

    marks = _section_marks(t)
    out: list[tuple[str, str]] = []

    if marks:
        head = t[: marks[0][0]].strip()
        if len(head) >= min_len:
            out.append(("header", head))
        for i, (start, num) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(t)
            body = t[start:end].strip()
            if body:
                out.append((str(num), body))
        return out

    # 폴백: 문장 분할. 절 서식이 아닌 짧은 통지문이 여기로 온다.
    parts = [p.strip() for p in _SENT.split(t) if p and p.strip()]
    if not parts:
        parts = [t]
    return [(f"s{i + 1}", p) for i, p in enumerate(parts)]


def segment_texts(text: str | None) -> list[str]:
    return [b for _, b in segments(text)]


# ── 예고(안내공시) 판별 ─────────────────────────────────────────────────────

# "기업가치 제고 계획 **예고**(안내공시)" — 계획 본공시가 아니라 "곧 내겠다"는 알림이다.
# 실측 56건이며 전부 축=0·`no_targets`로 떨어져 있다(labeling-guide §2-A).
#
# ⚠️ [2026-08-07] **정의를 여기서 갖지 않는다.** 이 모듈은 원래 자체 정규식
# (`예고\s*\(?\s*안내공시|계획\s*예고`, 머리말 한정)을 갖고 있었는데, 같은 날 OQ-4를
# 닫으면서 운영 코드에도 `plan_signals.is_notice`가 생겼다 — **같은 개념의 정의가 둘**이
# 된 것이다. 실측상 그날은 둘 다 정확히 56건으로 일치했지만, 갈라지는 것은 시간 문제다
# (`lookahead.py`에서 배운 것: 복제하면 갈라진다). 운영 정의를 권위로 삼고 여기서는
# 재수출만 한다 — 실험 트랙이 화면·워크리스트와 **다른 모수로 평가하는 일**을 막는다.
#
# 운영 정의는 제목 서식(`…예고(안내공시)/(`)을 요구한다. 이유는 그쪽 docstring 참조 —
# 단순 포함으로 잡으면 `axis_targets` 40건이 예고로 뒤집힌다(자기 예고를 관련공시로
# 나열한 진짜 계획들).


def is_notice(text: str | None) -> bool:
    """계획 예고(안내공시)인가 — 판정은 `plan_signals.is_notice`가 소유한다.

    **학습 모수에서 제외하는 기준**이라는 쓰임은 이 모듈 것이다. 제외 이유는 두 가지다.
    (1) 머리말 문자열로 100% 갈리므로 학습할 것이 없다.
    (2) 축=0 구간 206건 중 56건(27%)이 이 정형 문서라, 남겨두면 어휘 baseline도 거의 다
    맞혀 macro-F1이 통째로 부풀려진다. 제외 사실과 건수는 항상 함께 보고한다.
    """
    return _prod_is_notice(text)


# ── 3. 검증 — 전처리가 신호를 죽이지 않았는가 ───────────────────────────────

# 판정 신호의 원형. 전처리 후에도 살아 있어야 한다(하나라도 죽으면 전처리가 틀린 것).
_SIGNAL_PROBES = (
    ("첨부부존재선언", lambda s: any(k in re.sub(r"\s+", "", s)
                                     for k in ("첨부없이", "첨부를생략", "첨부서류를생략", "첨부생략"))),
    ("재공시참조", lambda s: bool(re.search(r"(?:旣|기)\s*공시", s))),
)


def _verify(rows: list[dict]) -> list[dict]:
    """원문에 있던 신호가 정제본에서 사라진 경우를 모은다."""
    lost = []
    for r in rows:
        raw, cln = r["raw_text"] or "", clean(r["raw_text"])
        for name, probe in _SIGNAL_PROBES:
            if probe(raw) and not probe(cln):
                lost.append({"plan_id": r["plan_id"], "signal": name})
    return lost


def main() -> int:
    con = sqlite3.connect(ROOT / "valueup.db")
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT plan_id, body_signal, attachment_absent, raw_text FROM valueup_plan")]
    con.close()

    raw_len = [len(r["raw_text"] or "") for r in rows]
    cln = [clean(r["raw_text"]) for r in rows]
    cln_len = [len(c) for c in cln]
    segs = [segments(r["raw_text"]) for r in rows]
    n_seg = [len(s) for s in segs]
    n_fallback = sum(1 for s in segs if s and s[0][0].startswith("s"))

    def p(xs, q):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(len(xs) * q))]

    print(f"# n={len(rows)}\n")
    print("## 1. 스타일시트 제거")
    print(f"  원문 평균   {statistics.mean(raw_len):>7.0f}자")
    print(f"  정제 평균   {statistics.mean(cln_len):>7.0f}자   "
          f"(제거율 {1 - statistics.mean(cln_len) / statistics.mean(raw_len):.1%})")
    print(f"  정제 길이   p10={p(cln_len, .1)} p50={p(cln_len, .5)} p90={p(cln_len, .9)} max={max(cln_len)}")
    empty = sum(1 for c in cln_len if c == 0)
    print(f"  본문 소실   {empty}건 {'← 0이어야 정상' if empty else '(정상)'}\n")

    print("## 2. 절 분할")
    print(f"  절 개수     p10={p(n_seg, .1)} p50={p(n_seg, .5)} p90={p(n_seg, .9)} max={max(n_seg)}")
    print(f"  번호 절 인식 {len(rows) - n_fallback}건 / 문장 폴백 {n_fallback}건")
    print(f"  bag 비어있음 {sum(1 for k in n_seg if k == 0)}건 (0이어야 정상)\n")

    print("## 3. 신호 보존 검증")
    lost = _verify(rows)
    print(f"  원문에 있던 신호가 정제본에서 소실: {len(lost)}건 {'← 실패' if lost else '(통과)'}")
    for x in lost[:10]:
        print(f"    - plan {x['plan_id']}: {x['signal']}")
    print()

    print("## 4. 신호가 실린 절의 위치 (MIL bag 설계 근거)")
    where: dict[str, int] = {}
    for r, s in zip(rows, segs):
        for label, body in s:
            if re.search(r"(?:旣|기)\s*공시", body) or "첨부없이" in re.sub(r"\s+", "", body):
                where[label] = where.get(label, 0) + 1
    for label, k in sorted(where.items(), key=lambda kv: -kv[1]):
        print(f"    절 {label:<8} {k:>4}건")
    print("  → 신호가 특정 절에 몰릴수록 mean pooling의 희석이 크다(max/attention 근거).")

    return 1 if (lost or empty) else 0


if __name__ == "__main__":
    raise SystemExit(main())
