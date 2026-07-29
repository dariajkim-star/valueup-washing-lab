"""sprint-status.yaml 정합성 — 문서 규율을 테스트로 강제한다.

파티 결정(2026-07-29): "에픽 done 시 회고 확인"을 사람 체크리스트가 아니라 절차로.
v2에서 회고 누락이 3연속이었고(epic 4·5·6), 그 대가가 2주치 거짓 문서였다.
사람이 지키는 규율은 v2에서 이미 실패했다 — 기계가 잡는다.

검사 계약:
  1. `epic-N: done`이면 `epic-N-retrospective: done`이 있어야 한다.
  2. 회고 done이 주석으로 가리키는 회고 파일(*-retro-*.md)이 실재해야 한다 —
     문서가 없는 경로를 가리키는 것은 문서가 거짓말하는 것이다(Paige).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "docs" / "implementation-artifacts" / "sprint-status.yaml"


def _development_status_lines() -> list[str]:
    """development_status 블록의 원문 줄들(주석 포함 — 회고 파일명이 주석에 있다)."""
    text = STATUS.read_text(encoding="utf-8")
    lines = text.splitlines()
    out: list[str] = []
    inside = False
    for ln in lines:
        if ln.startswith("development_status:"):
            inside = True
            continue
        if inside and re.match(r"^\S", ln):  # 다음 최상위 키에서 종료
            break
        if inside:
            out.append(ln)
    assert out, "development_status 블록을 찾지 못했다 — 파일 구조가 바뀌었으면 이 테스트를 갱신하라"
    return out


def _entries() -> dict[str, tuple[str, str]]:
    """키 → (상태, 원문 줄). 주석 줄은 건너뛴다."""
    entries: dict[str, tuple[str, str]] = {}
    for ln in _development_status_lines():
        m = re.match(r"^\s{2}([\w-]+):\s*([\w-]+)", ln)
        if m and not ln.lstrip().startswith("#"):
            entries[m.group(1)] = (m.group(2), ln)
    return entries


def test_done_epic_has_done_retrospective():
    """epic done ↔ 회고 done. v2에서 3연속 누락된 바로 그 구멍."""
    entries = _entries()
    epics = {k: v for k, v in entries.items() if re.fullmatch(r"epic-\d+", k)}
    assert epics, "epic 항목이 하나도 없다"
    missing = []
    for name, (status, _) in epics.items():
        if status != "done":
            continue
        retro = entries.get(f"{name}-retrospective")
        if retro is None or retro[0] != "done":
            missing.append(name)
    assert not missing, (
        f"done 에픽에 회고가 없다: {missing} — 회고를 실시하고 "
        f"{[m + '-retrospective: done' for m in missing]}을 기재하라 (통합 회고로 갈음 시 그 사실을 주석에)"
    )


def test_referenced_retro_files_exist():
    """회고 줄이 가리키는 *-retro-*.md 파일이 실재해야 한다."""
    docs = STATUS.parent
    broken = []
    for ln in _development_status_lines():
        for fname in re.findall(r"([\w-]+retro[\w-]*\.md)", ln):
            if not (docs / fname).exists():
                broken.append(fname)
    assert not broken, f"sprint-status가 없는 회고 파일을 가리킨다: {sorted(set(broken))}"
