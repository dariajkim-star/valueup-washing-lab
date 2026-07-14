import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { GapCard } from "./GapCard";
import type { GapDetail } from "../../api/detail";

afterEach(cleanup);

// 3.4 재리뷰 High — `v ? v*100 : null` truthiness가 정상값 0을 "—"(판단불가)로 세탁하던
// 버그의 회귀 테스트. 0%와 null은 다른 의미다(백엔드 null≠0 계약의 프론트 연장).

function gap(partial: Partial<GapDetail>): GapDetail {
  return {
    corp_code: "00000000", corp_name: null, market: null, as_of: "2026-07-13",
    target_roe: null, actual_roe: null, roe_gap: null, achievement_rate: null,
    progress_rate: null, execution_score: null, washing_flag: null, buyback_status: null,
    ...partial,
  };
}

describe("GapCard — 0과 null 구분", () => {
  it("achievement_rate=0·progress_rate=0은 '0.0%'로 표시된다('—' 금지)", () => {
    render(<GapCard gap={gap({ achievement_rate: 0, progress_rate: 0 })} />);
    const zeros = screen.getAllByText("0.0%");
    expect(zeros).toHaveLength(2); // 달성률·진척률 둘 다
  });

  it("achievement_rate=null은 '—'", () => {
    render(<GapCard gap={gap({ achievement_rate: null, progress_rate: 0.5 })} />);
    expect(screen.getByText("50.0%")).toBeTruthy();
    // 달성률 자리는 — (다른 null 필드들도 —라 최소 1개 이상)
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("roe_gap=null은 회색(—)이고 빨간색(부정 신호)이 아니다", () => {
    render(<GapCard gap={gap({ roe_gap: null })} />);
    // 갭 Stat의 값 요소를 찾아 색 확인 — null은 #9ca3af(중립 회색)
    const dashes = screen.getAllByText("—");
    const gapStat = dashes.find((el) => (el as HTMLElement).style.color === "rgb(156, 163, 175)");
    expect(gapStat).toBeTruthy();
  });

  it("roe_gap 음수는 빨간색, 양수는 초록색", () => {
    const { unmount } = render(<GapCard gap={gap({ roe_gap: -3.2 })} />);
    expect((screen.getByText("-3.2%p") as HTMLElement).style.color).toBe("rgb(220, 38, 38)");
    unmount();
    render(<GapCard gap={gap({ roe_gap: 2.1 })} />);
    expect((screen.getByText("+2.1%p") as HTMLElement).style.color).toBe("rgb(14, 159, 110)");
  });

  it("gap=null(성공+빈결과)이면 미집계 안내", () => {
    render(<GapCard gap={null} />);
    expect(screen.getByText(/엔진 미집계/)).toBeTruthy();
  });
});
