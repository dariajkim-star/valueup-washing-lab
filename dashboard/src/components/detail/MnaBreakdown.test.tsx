import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MnaBreakdown } from "./MnaBreakdown";
import type { MnaDetail } from "../../api/detail";

afterEach(cleanup);

// 3.4 재리뷰 Med — 상세 화면도 리스트(MnaCell)와 동일하게 구조적 미지원 업종(KSIC 64~66)과
// 개별 데이터 결측을 구분해야 한다.

function mna(partial: Partial<MnaDetail>): MnaDetail {
  return {
    corp_code: "00000000", corp_name: null, market: null, sector: null, as_of: "2026-07-13",
    mna_target_score: null, valuation_score: null, capacity_score: null,
    ownership_score: null, macro_score: null, population_basis: null,
    ...partial,
  };
}

describe("MnaBreakdown — 산식 미적용 vs 산출 불가 구분", () => {
  it("은행(641xx) + 총점 null → 산식 미적용 안내", () => {
    render(<MnaBreakdown mna={mna({ sector: "64121", mna_target_score: null })} />);
    expect(screen.getByText(/산식 미적용/)).toBeTruthy();
    expect(screen.queryByText(/요소 지표 결측/)).toBeNull();
  });

  // [정정 2026-08-03] 지주회사도 KSIC 64다 — 상세도 목록과 같은 정정을 받는다.
  it("지주회사(64992) + 총점 null → 산출 불가(요소 결측)", () => {
    render(<MnaBreakdown mna={mna({ sector: "64992", mna_target_score: null })} />);
    expect(screen.getByText(/요소 지표 결측/)).toBeTruthy();
    expect(screen.queryByText(/산식 미적용/)).toBeNull();
  });

  it("비금융(26xxx) + 총점 null → 산출 불가(요소 결측) 안내", () => {
    render(<MnaBreakdown mna={mna({ sector: "26100", mna_target_score: null })} />);
    expect(screen.getByText(/요소 지표 결측/)).toBeTruthy();
    expect(screen.queryByText(/산식 미적용/)).toBeNull();
  });

  it("총점이 있으면 안내문 없음", () => {
    render(<MnaBreakdown mna={mna({ sector: "64121", mna_target_score: 55 })} />);
    expect(screen.queryByText(/산식 미적용/)).toBeNull();
    expect(screen.queryByText(/산출 불가/)).toBeNull();
  });

  it("mna=null(성공+빈결과) → 미집계 안내", () => {
    render(<MnaBreakdown mna={null} />);
    expect(screen.getByText(/엔진 미집계/)).toBeTruthy();
  });
});
