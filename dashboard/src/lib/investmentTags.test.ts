import { describe, expect, it } from "vitest";
import { hasTagBasis, mnaTags, valueupTags } from "./investmentTags";
import type { GapDetail, MnaDetail } from "../api/detail";
import type { ScreeningRow } from "../api/screening";

// 3.4 재리뷰 반영: roe/pbr 입력이 /metrics 시계열이 아니라 /screening 행(header)으로 변경 —
// 화면 전체가 header.as_of 단일 기준일로 수렴(시점 혼합 차단).

function header(partial: Partial<ScreeningRow>): ScreeningRow {
  return {
    corp_code: "00000000", corp_name: "테스트", market: "KOSPI", sector: "26100",
    as_of: "2026-07-13", roe: null, pbr: null, execution_score: null,
    washing_flag: null, buyback_status: null, buyback_executed: null,
    mna_target_score: null, population_basis: null,
    has_valueup_score: true, has_mna_score: true,
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
    expect(valueupTags(header({}), gap({}))).toEqual([]);
  });
  it("roe=10(경계값)은 고ROE — 임계 이상 포함", () => {
    const tags = valueupTags(header({ roe: 10 }), gap({}));
    expect(tags).toEqual([{ label: "고ROE (10.0%)", group: "valueup" }]);
  });
  it("roe=9.9는 고ROE 아님", () => {
    expect(valueupTags(header({ roe: 9.9 }), gap({}))).toEqual([]);
  });
  it("pbr=1.0(경계값)은 저PBR — 임계 이하 포함", () => {
    const tags = valueupTags(header({ pbr: 1.0 }), gap({}));
    expect(tags).toEqual([{ label: "저PBR (1.00x)", group: "valueup" }]);
  });
  it("buyback_status='unknown'(판단불가)은 태그 없음 — retired일 때만", () => {
    expect(valueupTags(header({}), gap({ buyback_status: "unknown" }))).toEqual([]);
    expect(valueupTags(header({}), gap({ buyback_status: "retired" }))).toEqual([
      { label: "자사주 실이행 (소각 확인)", group: "valueup" },
    ]);
  });
  it("header 자체가 null(스크리닝 행 없음)이어도 크래시 없이 동작", () => {
    expect(valueupTags(null, gap({ buyback_status: "retired" }))).toEqual([
      { label: "자사주 실이행 (소각 확인)", group: "valueup" },
    ]);
  });
  it("전 조건 충족 시 3개 태그", () => {
    const tags = valueupTags(header({ roe: 15, pbr: 0.8 }), gap({ buyback_status: "retired" }));
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

describe("hasTagBasis — 데이터부족(판단불가) vs 기준미충족 구분(3.4 재리뷰 Med)", () => {
  it("전 입력 null이면 근거 없음(데이터 부족)", () => {
    expect(hasTagBasis(header({}), gap({}), mna({}))).toBe(false);
    expect(hasTagBasis(null, null, null)).toBe(false);
  });
  it("지표가 있으나 임계 미달이면 근거 있음(기준 미충족으로 표시돼야)", () => {
    // roe=5%(<10 임계) — 태그는 안 생기지만 판단 근거는 존재
    expect(hasTagBasis(header({ roe: 5 }), gap({}), mna({}))).toBe(true);
    expect(valueupTags(header({ roe: 5 }), gap({}))).toEqual([]);
  });
  it("buyback_status만 있어도(비록 unknown이라도) 근거 있음", () => {
    expect(hasTagBasis(header({}), gap({ buyback_status: "none" }), mna({}))).toBe(true);
  });
});
