"""opacity_engine 검증 — 공시 불투명도 순위(washing_flag 후속, 파티 결정 2026-07-23).

순수 함수 단위 테스트. 설계 근거·실데이터 검증은 opacity_engine 모듈 docstring 참조.
핵심 계약 3가지를 못 박는다:
  1. opacity 축 4개 정의(pbr 제외, period 1축, payout=OR, buyback None만 미공시).
  2. 표지 통지문 제외는 **첨부 참조 AND 본문 count==최대**일 때만(기아 count=0 오제외 방지).
  3. 순위는 mna와 동형 — 불투명 많을수록 높은 백분위, 동점 mid-rank, small-N 시장 폴백.
"""

from __future__ import annotations

from app.analysis.opacity_engine import (
    is_cover_notice,
    opacity_axes,
    opacity_count,
    rank_from_plans,
    rank_opacity,
    references_attachment,
)

# ── 축 정의 ──


def _plan(**over: object) -> dict[str, object]:
    """4축 전부 공시한(=불투명 0) 계획을 기준으로, 넘긴 필드만 덮어쓴다."""
    base: dict[str, object] = {
        "target_roe": 10.0,
        "target_payout_ratio": 30.0,
        "target_total_return_ratio": None,
        "period_start": "2024",
        "buyback_planned": True,
        "raw_text": "ROE 10% 배당성향 30% 2024~2026 자사주 취득",
    }
    base.update(over)
    return base


def test_fully_disclosed_plan_has_zero_opacity() -> None:
    assert opacity_count(_plan()) == 0
    assert opacity_axes(_plan()) == {
        "roe": False,
        "payout": False,
        "period": False,
        "buyback": False,
    }


def test_empty_plan_has_max_opacity() -> None:
    """4축 전부 null → count 4(최대)."""
    plan = _plan(
        target_roe=None,
        target_payout_ratio=None,
        target_total_return_ratio=None,
        period_start=None,
        buyback_planned=None,
    )
    assert opacity_count(plan) == 4


def test_payout_axis_is_or_of_two_return_metrics() -> None:
    """배당성향·총주주환원율은 대체재 — 하나만 있어도 '환원 공시'(불투명 아님)."""
    # 배당성향만 공시
    assert opacity_axes(_plan(target_payout_ratio=30.0, target_total_return_ratio=None))[
        "payout"
    ] is False
    # 총주주환원율만 공시
    assert opacity_axes(_plan(target_payout_ratio=None, target_total_return_ratio=50.0))[
        "payout"
    ] is False
    # 둘 다 null일 때만 환원 불투명
    assert opacity_axes(_plan(target_payout_ratio=None, target_total_return_ratio=None))[
        "payout"
    ] is True


def test_buyback_false_is_disclosed_not_opaque() -> None:
    """buyback_planned=False는 '자사주 계획 없음'을 **공시한** 것 → 불투명 아님. None만 미공시."""
    assert opacity_axes(_plan(buyback_planned=False))["buyback"] is False
    assert opacity_axes(_plan(buyback_planned=None))["buyback"] is True


def test_pbr_is_not_an_opacity_axis() -> None:
    """target_pbr(100% null·산식 미사용)은 축에 없다 — 넣어도 count 불변."""
    assert opacity_count(_plan(target_pbr=None)) == 0
    assert opacity_count(_plan(target_pbr=1.5)) == 0


# ── 표지 통지문 제외 ──


def test_references_attachment_detects_notice_phrase() -> None:
    assert references_attachment("상세한 내용은 첨부된 '기업가치 제고 계획'을 참고하시기 바랍니다")
    assert references_attachment("세부사항은 첨부된 이행 현황을 참고")
    assert not references_attachment("ROE 10% 배당성향 30% 자사주 취득")


def test_cover_notice_requires_attachment_ref_AND_max_opacity() -> None:
    """제외는 첨부 참조 **그리고** 본문 count==최대일 때만(실데이터로 강화된 조건)."""
    ref = "상세한 내용은 첨부된 '기업가치 제고 계획'을 참고하시기 바랍니다"
    # 본문 텅 빔 + 첨부 참조 → 표지 통지문(제외 대상)
    shell = _plan(
        target_roe=None, target_payout_ratio=None, target_total_return_ratio=None,
        period_start=None, buyback_planned=None, raw_text=ref,
    )
    assert is_cover_notice(shell) is True
    # 본문에 목표 다 있고 + 첨부 참조 → 멀쩡한 공시(기아 케이스). 제외 안 함.
    rich = _plan(raw_text="ROE 10% 배당성향 30% 2024~2026 자사주 취득. " + ref)
    assert opacity_count(rich) == 0
    assert is_cover_notice(rich) is False


def test_max_opacity_without_attachment_is_not_excluded() -> None:
    """본문 텅 비었어도 첨부 참조가 없으면 제외 아님 — 그건 진짜 불투명(순위 대상)."""
    opaque = _plan(
        target_roe=None, target_payout_ratio=None, target_total_return_ratio=None,
        period_start=None, buyback_planned=None, raw_text="기업가치 제고 계획입니다.",
    )
    assert opacity_count(opaque) == 4
    assert is_cover_notice(opaque) is False


# ── peer 상대 순위 ──


def _sectors(**m: str) -> dict[str, str | None]:
    return dict(m)


def test_rank_higher_count_gets_higher_rank() -> None:
    """불투명 많을수록 높은 백분위. 버킷 미상 → market."""
    counts = {"a": 0, "b": 1, "c": 2, "d": 3}
    sectors: dict[str, str | None] = {c: None for c in counts}
    ranks = rank_opacity(counts, sectors, peer_min=5)
    r = {c: ranks[c][0] for c in counts}
    assert r["a"] == 0.0
    assert r["d"] == 1.0
    assert r["a"] < r["b"] < r["c"] < r["d"]
    assert all(b == "market" for _, b in ranks.values())


def test_rank_ties_use_mid_rank() -> None:
    """전원 동일 count → 0.5(중립, mna와 동일 mid-rank)."""
    counts = {"a": 2, "b": 2, "c": 2}
    ranks = rank_opacity(counts, {c: None for c in counts}, peer_min=5)
    assert all(ranks[c][0] == 0.5 for c in counts)


def test_rank_sector_bucket_when_peers_sufficient() -> None:
    """같은 KSIC 버킷 유효 peer>=peer_min이면 sector 백분위(basis=sector:NN)."""
    counts = {c: i % 4 for i, c in enumerate("abcde")}
    sectors = {c: "26xx" for c in counts}  # 앞 2자리 '26' 동일 버킷
    ranks = rank_opacity(counts, sectors, peer_min=5)
    assert all(b == "sector:26" for _, b in ranks.values())


def test_rank_market_fallback_when_peers_insufficient() -> None:
    """버킷 peer가 peer_min 미달이면 시장 폴백(basis=market_fallback)."""
    counts = {"a": 0, "b": 1, "c": 2}
    sectors = {c: "2610" for c in counts}  # 버킷 '26' peer 3 < 5
    ranks = rank_opacity(counts, sectors, peer_min=5)
    assert all(b == "market_fallback" for _, b in ranks.values())


def test_rank_single_company_bucket_is_none() -> None:
    """유효 peer<2면 순위 불가(None) — mna와 동일 계약."""
    ranks = rank_opacity({"solo": 2}, {"solo": None}, peer_min=5)
    assert ranks["solo"] == (None, None)


def test_rank_from_plans_excludes_only_shells() -> None:
    """표지 통지문(첨부+count최대)만 모집단에서 빠지고, 본문 공시자는 순위에 남는다."""
    ref = "상세한 내용은 첨부된 계획을 참고"
    plans = {
        "kia": _plan(),  # count 0
        "shell": _plan(
            target_roe=None, target_payout_ratio=None, target_total_return_ratio=None,
            period_start=None, buyback_planned=None, raw_text=ref,
        ),  # count 4 + 첨부 → 제외
        "opaque": _plan(
            target_roe=None, target_payout_ratio=None, target_total_return_ratio=None,
            period_start=None, buyback_planned=None, raw_text="목표 없음",
        ),  # count 4, 첨부 없음 → 순위에 남음
    }
    sectors: dict[str, str | None] = {c: None for c in plans}
    ranks = rank_from_plans(plans, sectors, peer_min=5)
    assert "shell" not in ranks  # 제외 = 순위 dict에 없음
    assert ranks["kia"][0] == 0.0  # 전부 공시 → 최저 불투명
    assert ranks["opaque"][0] == 1.0  # 본문 텅 + 첨부 없음 → 최고 불투명
