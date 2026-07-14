import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_SORT, MCAP_BOUNDS, toParams, useFilters } from "./filters";

// zustand 스토어는 모듈 전역 — 테스트마다 초기 상태로 리셋
const initial = useFilters.getState();
beforeEach(() => useFilters.setState(initial, true));

describe("filters store (3.3 리뷰 반영)", () => {
  it("시장 변경 시 page=1 리셋", () => {
    useFilters.getState().setPage(3);
    useFilters.getState().setMarket("KOSDAQ");
    expect(useFilters.getState().page).toBe(1);
    expect(useFilters.getState().market).toBe("KOSDAQ");
  });

  it("스코어 모드 전환 시 기본 sort 스왑 + page 리셋 (AC6)", () => {
    useFilters.getState().setPage(2);
    useFilters.getState().setScoreMode("mna");
    const s = useFilters.getState();
    expect(s.sort).toBe(DEFAULT_SORT.mna); // -mna_target_score
    expect(s.page).toBe(1);
    useFilters.getState().setScoreMode("valueup");
    expect(useFilters.getState().sort).toBe(DEFAULT_SORT.valueup); // execution_score
  });

  it("사용자 정렬 후 모드 전환하면 기본 정렬로 덮인다(모드 관점 우선)", () => {
    useFilters.getState().setSort("-execution_score");
    useFilters.getState().setScoreMode("mna");
    expect(useFilters.getState().sort).toBe("-mna_target_score");
  });

  it("patch(지표 필터)도 page=1 리셋", () => {
    useFilters.getState().setPage(5);
    useFilters.getState().patch({ minRoe: 10 });
    const s = useFilters.getState();
    expect(s.page).toBe(1);
    expect(s.minRoe).toBe(10);
  });

  it("toParams: 시총 버킷 → min/max_market_cap 변환", () => {
    useFilters.getState().setMcapBucket("mid");
    const p = toParams(useFilters.getState());
    expect(p.min_market_cap).toBe(MCAP_BOUNDS.mid.min);
    expect(p.max_market_cap).toBe(MCAP_BOUNDS.mid.max);
  });

  it("toParams: washing_only=false는 undefined로(파라미터 미전송)", () => {
    const p = toParams(useFilters.getState());
    expect(p.washing_only).toBeUndefined();
    useFilters.getState().setWashingOnly(true);
    expect(toParams(useFilters.getState()).washing_only).toBe(true);
  });
});
