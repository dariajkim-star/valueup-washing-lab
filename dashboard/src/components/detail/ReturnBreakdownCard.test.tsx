import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

afterEach(cleanup);
import { ReturnBreakdownCard } from "./ReturnBreakdownCard";
import type { ReturnBreakdownPoint } from "../../api/detail";

// [2026-08-04] 환원율 점프 설명 카드 — null 계약(0 세탁 금지)과 점프 배지 조건 검증.
// 실측 모델: 에이피알 2023년 0% → 2024년 55.7%(증가분 전액 자사주 취득).

function pt(partial: Partial<ReturnBreakdownPoint> & { year: number }): ReturnBreakdownPoint {
  return {
    dividend_total: null,
    buyback_amount_krw: null,
    buyback_retired_qty: null,
    net_income: null,
    total_return_ratio: null,
    payout_ratio: null,
    ...partial,
  };
}

const APR_2023 = pt({
  year: 2023, dividend_total: 0, buyback_amount_krw: 0, buyback_retired_qty: 0,
  net_income: 81_546_050_952, total_return_ratio: 0.0, payout_ratio: 0.0,
});
const APR_2024 = pt({
  year: 2024, dividend_total: 0, buyback_amount_krw: 59_943_891_000, buyback_retired_qty: 0,
  net_income: 107_590_435_967, total_return_ratio: 55.7, payout_ratio: 0.0,
});

describe("ReturnBreakdownCard", () => {
  it("연도별 환원율과 YoY 점프 배지를 보여준다(±10%p 이상일 때만)", () => {
    render(<ReturnBreakdownCard rows={[APR_2023, APR_2024]} />);
    expect(screen.getByText("0.0%")).toBeTruthy();
    expect(screen.getByText("55.7%")).toBeTruthy();
    expect(screen.getByText(/\+55\.7%p YoY/)).toBeTruthy();
  });

  it("변화가 10%p 미만이면 점프 배지를 띄우지 않는다(모든 변화를 점프라 부르지 않는다)", () => {
    const y1 = pt({ ...APR_2024, year: 2023, total_return_ratio: 50.0 });
    const y2 = pt({ ...APR_2024, year: 2024, total_return_ratio: 55.7 });
    render(<ReturnBreakdownCard rows={[y1, y2]} />);
    expect(screen.queryByText(/YoY/)).toBeNull();
  });

  it("분자 구성이 미상(null)인 해는 —로 남긴다 — 0%로 세탁 금지", () => {
    const unknown = pt({ year: 2022, net_income: 100 }); // 배당·취득 null → 뷰도 null
    render(<ReturnBreakdownCard rows={[unknown, APR_2023, APR_2024]} />);
    const dash = screen.getByTitle(/산출 불가/);
    expect(dash.textContent).toBe("—");
  });

  it("최신 연도가 취득>0 + 소각 수량 0이면 '매입만 · 소각 0' 배지", () => {
    render(<ReturnBreakdownCard rows={[APR_2023, APR_2024]} />);
    expect(screen.getByText("매입만 · 소각 0")).toBeTruthy();
  });

  it("소각 수량 미상(null)이면 배지를 띄우지 않는다 — 못 읽은 걸 판정하지 않는다", () => {
    const latest = pt({ ...APR_2024, buyback_retired_qty: null });
    render(<ReturnBreakdownCard rows={[APR_2023, latest]} />);
    expect(screen.queryByText("매입만 · 소각 0")).toBeNull();
  });

  it("취득이 0이면 소각 0이어도 배지가 없다 — '매입만'은 매입을 전제한다", () => {
    render(<ReturnBreakdownCard rows={[APR_2023]} />);
    expect(screen.queryByText("매입만 · 소각 0")).toBeNull();
  });

  it("행이 없으면 데이터 없음을 말한다(빈 차트로 위장하지 않음)", () => {
    render(<ReturnBreakdownCard rows={[]} />);
    expect(screen.getByText("연간 재무 데이터 없음")).toBeTruthy();
  });
});
