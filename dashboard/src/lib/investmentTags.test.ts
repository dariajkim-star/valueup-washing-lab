import { describe, expect, it } from "vitest";
import { mnaTags, valueupTags } from "./investmentTags";
import type { GapDetail, MetricPoint, MnaDetail } from "../api/detail";

function metric(partial: Partial<MetricPoint>): MetricPoint {
  return {
    corp_code: "00000000", corp_name: null, market: null, sector: null,
    year: 2025, quarter: 3, roe: null, roa: null, pbr: null, per: null,
    ev_ebitda: null, debt_ratio: null, payout_ratio: null, net_cash: null,
    ebitda_margin: null, yoy_revenue_growth: null, yoy_income_growth: null,
    ...partial,
  };
}

function gap(partial: Partial<GapDetail>): GapDetail {
  return {
    corp_code: "00000000", corp_name: null, market: null, as_of: "2026-07-13",
    target_roe: null, actual_roe: null, roe_gap: null, achievement_rate: null,
    progress_rate: null, execution_score: null, washing_flag: null, buyback_status: null,
    ...partial,
  };
}

function mna(partial: Partial<MnaDetail>): MnaDetail {
  return {
    corp_code: "00000000", corp_name: null, market: null, sector: null, as_of: "2026-07-13",
    mna_target_score: null, valuation_score: null, capacity_score: null,
    ownership_score: null, macro_score: null, population_basis: null,
    ...partial,
  };
}

describe("valueupTags — null이면 태그 미생성", () => {
  it("roe·pbr·buyback_status 전부 null이면 태그 없음", () => {
    expect(valueupTags(metric({}), gap({}))).toEqual([]);
  });
  it("roe=10(경계값)은 고ROE — 임계 이상 포함", () => {
    const tags = valueupTags(metric({ roe: 10 }), gap({}));
    expect(tags).toEqual([{ label: "고ROE (10.0%)", group: "valueup" }]);
  });
  it("roe=9.9는 고ROE 아님", () => {
    expect(valueupTags(metric({ roe: 9.9 }), gap({}))).toEqual([]);
  });
  it("pbr=1.0(경계값)은 저PBR — 임계 이하 포함", () => {
    const tags = valueupTags(metric({ pbr: 1.0 }), gap({}));
    expect(tags).toEqual([{ label: "저PBR (1.00x)", group: "valueup" }]);
  });
  it("buyback_status='unknown'(판단불가)은 태그 없음 — retired일 때만", () => {
    expect(valueupTags(metric({}), gap({ buyback_status: "unknown" }))).toEqual([]);
    expect(valueupTags(metric({}), gap({ buyback_status: "retired" }))).toEqual([
      { label: "자사주 실이행 (소각 확인)", group: "valueup" },
    ]);
  });
  it("latestMetric 자체가 undefined(지표 없음)여도 크래시 없이 빈 배열", () => {
    expect(valueupTags(undefined, gap({ buyback_status: "retired" }))).toEqual([
      { label: "자사주 실이행 (소각 확인)", group: "valueup" },
    ]);
  });
  it("전 조건 충족 시 3개 태그", () => {
    const tags = valueupTags(metric({ roe: 15, pbr: 0.8 }), gap({ buyback_status: "retired" }));
    expect(tags).toHaveLength(3);
  });
});

describe("mnaTags — null이면 태그 미생성, 산출불가(mna=null)는 완전 빈 배열", () => {
  it("mna 자체가 null(산출 불가)이면 빈 배열", () => {
    expect(mnaTags(null)).toEqual([]);
  });
  it("요소 전부 null이면 태그 없음(총점은 있어도 요소가 null일 수 있는 이론상 케이스 방어)", () => {
    expect(mnaTags(mna({ mna_target_score: 50 }))).toEqual([]);
  });
  it("valuation_score=0.7(경계)은 저평가 포함", () => {
    expect(mnaTags(mna({ valuation_score: 0.7 }))).toEqual([{ label: "저평가", group: "mna" }]);
  });
  it("valuation_score=0.69는 저평가 아님", () => {
    expect(mnaTags(mna({ valuation_score: 0.69 }))).toEqual([]);
  });
  it("3요소 전부 강함이면 3개 태그", () => {
    const tags = mnaTags(mna({ valuation_score: 0.9, capacity_score: 0.8, ownership_score: 0.75 }));
    expect(tags).toHaveLength(3);
    expect(tags.map((t) => t.label)).toEqual(["저평가", "저부채", "낮은 지분율"]);
  });
});
