"""opacity_engine — 공시 불투명도 순위(washing_flag 후속, 파티 결정 2026-07-23).

washing_flag는 '고의(워싱 의심)'를 판정해 프로젝트 서명("불확실을 확실로 세탁하지 않는다")을
위반했고, 실측 True=0이었다 — target_roe 58%·buyback_planned 48% null인 표본에서 4치 AND가
전항 확정 True가 될 일이 구조적으로 거의 없어, **켜질 수 없는 경고등**이었다(버그 아님, 은퇴 대상).

그 자리를 대체하는 것이 opacity_rank. '고의'가 아니라 **격차** — 공시하지 않은 목표 축의 수를
peer(같은 KSIC 버킷) 대비 백분위로 순위화한다(레아 원칙: "고의를 판정하지 말고 격차를 드러내라").
입력은 valueup_plan의 목표 공시 여부뿐, **신규 수집 없음**.

구조는 mna_engine과 동형(peer 백분위 + 섹터 버킷 + 시장 폴백 + basis) — 그 원시함수를 재사용한다.

⚠️ 첨부 사각지대(2026-07-23 라이브 실측):
    대기업 다수가 실계획을 PDF/HWP **첨부**로 내고 document.xml엔 "첨부 참조" 표지 통지문만
    남긴다(SK하이닉스·LG에너지솔루션·KB금융·하나금융·삼성화재 — all-null 20건 중 11건).
    이들을 모집단에 넣으면 opacity_count가 최대로 잡혀 '가장 불투명한 워싱 기업'으로 **오인**된다
    — 실제로는 기계가독 형식으로 안 냈을 뿐 목표는 공시했다. 그래서 표지 통지문은 모집단에서
    **제외**한다(is_cover_notice). 첨부 본문 수집(DART 웹뷰어 스크래핑 + PDF/HWP 파싱)은
    OpenAPI 범위 밖이라 별도 백로그 스토리로 분리했다(오늘 결정 ②).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from app.analysis.mna_engine import _pct_rank_high, _sector_bucket

# ── 불투명 축(4개) ──
# 각 축이 null이면 "그 목표를 공시하지 않음" = 1점. 설계 근거(파티 2026-07-23):
#   - target_pbr 제외: 100% null이자 achievement 산식 미사용(gap_engine) → 변별력 0, 노이즈만.
#   - period: period_start/period_end는 항상 동반 null(둘 다 73%)이라 한 축으로 묶는다
#     (각각 세면 "기간 미공시"가 이중 가중).
#   - payout: 배당성향·총주주환원율은 **대체재**(하나만 약속해도 환원을 공시한 것)라 OR로 묶는다
#     (각각 세면 총주주환원율만 약속한 기업이 부당하게 불투명해진다 — Boundary 지적).
#   - buyback: None만 '미공시'. False는 "자사주 계획 없음"을 **공시한** 것이므로 불투명 아님
#     (_washing_flag가 buyback_planned를 3치로 다루는 것과 같은 기준).
_OPACITY_AXES = ("roe", "payout", "period", "buyback")


def opacity_axes(plan: Mapping[str, object]) -> dict[str, bool]:
    """계획의 목표 공시 여부 → 축별 '미공시(True=불투명)' 판정. 4축(위 설계 근거)."""
    return {
        "roe": plan.get("target_roe") is None,
        "payout": plan.get("target_payout_ratio") is None
        and plan.get("target_total_return_ratio") is None,
        "period": plan.get("period_start") is None,
        "buyback": plan.get("buyback_planned") is None,
    }


def opacity_count(plan: Mapping[str, object]) -> int:
    """공시하지 않은 축의 수(0~4). 높을수록 불투명."""
    return sum(opacity_axes(plan).values())


# ── 표지 통지문 제외(첨부 사각지대 방어) ──
# document.xml이 "상세한 내용은 첨부된 …을 참고하시기 바랍니다" 류면 본문에 목표가 없어도
# 미공시가 아니라 **비가독 공시**다. 이런 통지문은 opacity 모집단에서 뺀다(rank=None).
# 실샘플 문구: "상세한 내용은 첨부된 '기업가치 제고 계획'을 참고", "세부사항은 첨부된 …",
# "보다 자세한 내용은 첨부된 …". 첨부/별첨 뒤 짧은 구간에 참고·참조·계획·내용·현황이 오는 형태.
_COVER_NOTICE_RE = re.compile(r"(?:첨부|별첨)[^\n]{0,25}?(?:참고|참조|계획|내용|현황)")


def references_attachment(raw_text: str | None) -> bool:
    """본문이 첨부 문서를 참조하는가(그 문서에 상세 계획이 있다는 안내)."""
    return bool(_COVER_NOTICE_RE.search(raw_text or ""))


def is_cover_notice(plan: Mapping[str, object]) -> bool:
    """계획이 순위 불가한 **표지 통지문**인가 — 첨부를 참조하면서 **본문엔 목표가 하나도 없는** 경우.

    실데이터 검증(2026-07-23)으로 강화된 조건: "첨부 참조" 문구만으로 제외하면 본문에 목표를
    다 쓰고 첨부는 부록으로 붙인 멀쩡한 공시(기아 opacity_count=0, 셀트리온 0)까지 잡아먹는다
    (26종목 중 15개 과다 제외 → Boundary 지적). 그래서 **본문 미공시가 최대(count==4)일 때만**
    표지 통지문으로 본다 — 본문에 목표가 하나라도 있으면(count<4) 그 목표로 순위를 매긴다
    (첨부는 그때 부록일 뿐). 이 조건으로 제외는 3종목(SK하이닉스·우리금융·LG에너지솔루션)으로
    좁혀지고 순위 모집단이 살아난다.
    """
    return references_attachment(plan.get("raw_text")) and (  # type: ignore[arg-type]
        opacity_count(plan) == len(_OPACITY_AXES)
    )


# ── peer 상대 순위(mna_engine 패턴 재사용) ──
def _bucket_of(
    corp_code: str, sectors: Mapping[str, str | None], market_key: str
) -> str:
    """corp → KSIC 버킷 키(분류 불가는 시장 모집단으로)."""
    return _sector_bucket(sectors.get(corp_code)) or market_key


def rank_opacity(
    counts: Mapping[str, int],
    sectors: Mapping[str, str | None],
    peer_min: int,
    *,
    market_key: str = "__market__",
) -> dict[str, tuple[float | None, str | None]]:
    """corp별 opacity_count → (opacity_rank, basis). mna와 동형의 섹터/시장 폴백.

    - 같은 KSIC 버킷 안 유효 peer가 peer_min 이상이면 sector 백분위(basis="sector:NN"),
      미달이면 시장 전체로 폴백(basis="market_fallback"), 버킷 미상이면 "market".
    - 순위는 `_pct_rank_high`(불투명 많을수록 높은 순위). 동점은 mid-rank(mna와 동일)라
      "전원 같은 수준" 버킷은 0.5로 중립. 유효 peer<2면 None(mna와 동일 계약).

    counts에서 제외된 종목(표지 통지문 등)은 애초에 넘기지 않는다 — 모집단·순위 양쪽에서 빠진다.
    """
    # 버킷별 count 모집단
    sector_pop: dict[str, list[float]] = {}
    market_pop: list[float] = []
    for corp_code, cnt in counts.items():
        bucket = _bucket_of(corp_code, sectors, market_key)
        sector_pop.setdefault(bucket, []).append(float(cnt))
        market_pop.append(float(cnt))

    # 버킷 승격 판정(small-N 노이즈 방어, mna_peer_min과 같은 기준)
    sector_ready = {
        b: len(pop) >= peer_min
        for b, pop in sector_pop.items()
        if b != market_key
    }

    out: dict[str, tuple[float | None, str | None]] = {}
    for corp_code, cnt in counts.items():
        bucket = _bucket_of(corp_code, sectors, market_key)
        if bucket == market_key:
            pop, basis = market_pop, "market"
        elif sector_ready.get(bucket, False):
            pop, basis = sector_pop[bucket], f"sector:{bucket}"
        else:
            pop, basis = market_pop, "market_fallback"
        rank = _pct_rank_high(float(cnt), pop)
        out[corp_code] = (rank, basis if rank is not None else None)
    return out


def rank_from_plans(
    plans: Mapping[str, Mapping[str, object]],
    sectors: Mapping[str, str | None],
    peer_min: int,
) -> dict[str, tuple[float | None, str | None]]:
    """corp별 **최신** 계획 dict → opacity_rank. 표지 통지문은 모집단에서 제외.

    plans[corp] 은 target_* 필드 + raw_text 를 가진 계획 한 건(최신)이어야 한다.
    """
    counts = {
        corp: opacity_count(plan)
        for corp, plan in plans.items()
        if not is_cover_notice(plan)
    }
    return rank_opacity(counts, sectors, peer_min)
