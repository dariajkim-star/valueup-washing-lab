import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render as rtlRender, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { GapCard } from "./GapCard";
import type { GapDetail } from "../../api/detail";

afterEach(cleanup);

// GapCard는 출처 블록에서 새로고침 mutation을 쓴다(2026-07-29) → QueryClient 필요.
// 재시도를 끄는 이유: 테스트가 네트워크 실패를 기다리며 늘어지지 않게.
function render(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return rtlRender(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

// 3.4 재리뷰 High — `v ? v*100 : null` truthiness가 정상값 0을 "—"(판단불가)로 세탁하던
// 버그의 회귀 테스트. 0%와 null은 다른 의미다(백엔드 null≠0 계약의 프론트 연장).

function gap(partial: Partial<GapDetail>): GapDetail {
  return {
    corp_code: "00000000", corp_name: null, market: null, as_of: "2026-07-13",
    target_roe: null, actual_roe: null, roe_gap: null, achievement_rate: null,
    progress_rate: null, execution_score: null, score_basis: null, washing_flag: null, buyback_status: null,
    plan_disclosure_date: null, plan_rcept_no: null,
    plan_is_fallback: false, plan_newest_disclosure_date: null,
    plan_body_signal: "axis_targets",
    excluded_axes: null, buyback_timing: null,
    target_payout_ratio: null, target_total_return_ratio: null,
    actual_payout_ratio: null, actual_total_return_ratio: null,
    payout_achievement: null, ambition: [],
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

describe("출처 표기(0015) — 목표값의 신선도를 감추지 않는다", () => {
  it("공시일과 DART 원문 링크를 접수번호로 조립한다", () => {
    render(<GapCard gap={gap({ plan_disclosure_date: "2024-11-27", plan_rcept_no: "20241127000123" })} />);
    expect(screen.getByText(/2024-11-27 공시/)).toBeTruthy();
    const link = screen.getByText("DART 원문") as HTMLAnchorElement;
    expect(link.href).toContain("rcpNo=20241127000123");
  });

  it("접수번호가 null이면 링크를 만들어내지 않고 이유를 말한다", () => {
    // 0015 이전 적재분 — 빈칸으로 뭉개면 사용자는 왜 원문에 못 가는지 알 수 없다.
    render(<GapCard gap={gap({ plan_disclosure_date: "2024-11-27", plan_rcept_no: null })} />);
    expect(screen.queryByText("DART 원문")).toBeNull();
    expect(screen.getByText(/접수번호 미보유/)).toBeTruthy();
  });

  it("[2026-07-29] 폴백이면 왜 최신 공시가 아닌지 말한다", () => {
    // 하나금융 실측 형태: 최신 2026-03-31은 표지 통지문이라 2024-10-29를 근거로 삼았다.
    // 공시일만 쓰면 사용자가 '낡은 데이터'로 오해한다 — 폴백 사실이 출처의 일부다.
    render(<GapCard gap={gap({
      plan_disclosure_date: "2024-10-29", plan_rcept_no: "20241029000111",
      plan_is_fallback: true, plan_newest_disclosure_date: "2026-03-31",
    })} />);
    expect(screen.getByText(/2024-10-29 공시 기준/)).toBeTruthy();
    expect(screen.getByText(/최신 공시\(2026-03-31\)에는 목표가 없어/)).toBeTruthy();
  });

  it("폴백이 아니면 그 안내를 띄우지 않는다", () => {
    render(<GapCard gap={gap({
      plan_disclosure_date: "2026-03-31", plan_rcept_no: "20260331000222",
      plan_is_fallback: false, plan_newest_disclosure_date: "2026-03-31",
    })} />);
    expect(screen.queryByText(/목표가 없어/)).toBeNull();
  });

  it("계획 공시 자체가 없으면 그렇게 말한다", () => {
    render(<GapCard gap={gap({ plan_disclosure_date: null, plan_rcept_no: null })} />);
    expect(screen.getByText("계획 공시 없음")).toBeTruthy();
  });

  it("업데이트 버튼이 있다", () => {
    render(<GapCard gap={gap({})} />);
    expect(screen.getByText("업데이트")).toBeTruthy();
  });

  it("[2026-07-29] 다른 지표로 공시한 회사를 부실 공시로 보이게 하지 않는다", () => {
    // LG엔솔 실측: 매출 2배·EBITDA Margin 10% 중반을 명확히 약속했다. 우리 축이 아닐 뿐.
    render(<GapCard gap={gap({ plan_body_signal: "other_metric" })} />);
    expect(screen.getByText(/우리가 재는 4축.*밖의 지표/)).toBeTruthy();
  });

  it("재공시는 그 사실을 말한다", () => {
    render(<GapCard gap={gap({ plan_body_signal: "refiling" })} />);
    expect(screen.getByText(/다른 공시를 가리키는 재공시/)).toBeTruthy();
  });

  it("정상(axis_targets)에는 설명을 붙이지 않는다 — 값이 이미 화면에 있다", () => {
    const { container } = render(<GapCard gap={gap({ plan_body_signal: "axis_targets" })} />);
    expect(container.textContent).not.toContain("밖의 지표");
    expect(container.textContent).not.toContain("재공시");
  });

  it("[2026-07-28] 자사주 라벨은 '이행'을 주장하지 않는다", () => {
    // buyback_status는 계획 기간과 무관한 직전 재무 기간 값 — 목록 배지와 같은 단어를 쓴다.
    render(<GapCard gap={gap({ buyback_status: "retired" })} />);
    expect(screen.getByText("최근 소각")).toBeTruthy();
  });
});

describe("[2026-07-31] 환원 축 — 만점의 근거를 화면이 말한다", () => {
  it("목표·실적·달성배율을 표시한다(한세실업 실측 형태)", () => {
    // 실측: 목표 배당성향 10% / 실적 33.7% → 100점. 점수만으론 이 사실이 안 보였다.
    render(<GapCard gap={gap({
      execution_score: 100, score_basis: "payout",
      target_payout_ratio: 10.0, actual_payout_ratio: 33.73, payout_achievement: 3.373,
    })} />);
    expect(screen.getByText("배당성향")).toBeTruthy();
    expect(screen.getByText(/목표 10\.0%/)).toBeTruthy();
    expect(screen.getByText(/실적 33\.7%/)).toBeTruthy();
    expect(screen.getByText("목표 대비 3.37배")).toBeTruthy();
  });

  it("총주주환원율이 있으면 그쪽을 쓴다(채점과 같은 우선순위)", () => {
    render(<GapCard gap={gap({
      target_payout_ratio: 20.0, target_total_return_ratio: 50.0,
      actual_payout_ratio: 25.0, actual_total_return_ratio: 55.0, payout_achievement: 1.1,
    })} />);
    expect(screen.getByText("총주주환원율")).toBeTruthy();
    expect(screen.getByText(/목표 50\.0%/)).toBeTruthy();
  });

  it("환원 축이 없으면 아예 렌더하지 않는다(빈 칸 노이즈 금지)", () => {
    const { container } = render(<GapCard gap={gap({ target_roe: 10 })} />);
    expect(container.textContent).not.toContain("목표 대비");
    expect(container.textContent).not.toContain("배당성향");
  });
});

describe("[2026-07-31] 제외된 축 — 못 잰 축이 조용히 사라지지 않는다", () => {
  it("기간 미상으로 ROE가 빠졌으면 그 사실과 이유를 말한다", () => {
    // 엘지이노텍 실측: 목표 ROE 15.0인데 계획 기간이 없어 ROE 축 제외, 배당성향으로만 채점.
    // score_basis에서 사라진 것만으론 "애초에 ROE를 약속 안 함"과 구분되지 않는다.
    render(<GapCard gap={gap({
      execution_score: 55.05, score_basis: "payout", excluded_axes: "roe:no_period",
      target_roe: 15.0, actual_roe: 8.39,
    })} />);
    expect(screen.getByText(/ROE는 채점에서 제외됨/)).toBeTruthy();
    expect(screen.getByText(/계획 기간이 공시에 없어/)).toBeTruthy();
  });

  it("제외된 축이 없으면 안내를 띄우지 않는다", () => {
    const { container } = render(<GapCard gap={gap({ excluded_axes: null })} />);
    expect(container.textContent).not.toContain("채점에서 제외");
  });
});

describe("[2026-07-31 P1-7] 목표의 야심도 — 점수가 아니라 격차 사실", () => {
  it("두 기준선을 나란히 보여준다(기아 실측: 자기 과거보단 낮고 업종보단 높다)", () => {
    // 하나의 점수로 압축했다면 사라졌을 사실 — 리드 결정 B의 근거 그 자체다.
    render(<GapCard gap={gap({
      ambition: [{
        metric: "roe", target: 15.0, baseline_year: 2023,
        own_past: 18.85, own_gap: -3.85,
        peer_median: 7.75, peer_gap: 7.25, peer_bucket: "30", peer_n: 10,
      }],
    })} />);
    expect(screen.getByText("목표의 야심도")).toBeTruthy();
    expect(screen.getByText("ROE")).toBeTruthy();
    expect(screen.getByText("-3.9%p")).toBeTruthy();   // 자기 과거 대비
    expect(screen.getByText("+7.3%p")).toBeTruthy();   // 업종 대비
  });

  it("업종 표본이 모자라면 빈칸이 아니라 이유를 말한다", () => {
    // 빈칸으로 두면 "업종과 같다"로 오독된다(한세실업 실측: KSIC 14, n=3).
    render(<GapCard gap={gap({
      ambition: [{
        metric: "payout_ratio", target: 10.0, baseline_year: 2024,
        own_past: 33.73, own_gap: -23.73,
        peer_median: null, peer_gap: null, peer_bucket: "14", peer_n: 3,
      }],
    })} />);
    expect(screen.getByText(/업종 표본 3개로 부족/)).toBeTruthy();
    expect(screen.getByText("-23.7%p")).toBeTruthy();
  });

  it("공시한 목표가 없으면 블록 자체를 그리지 않는다", () => {
    const { container } = render(<GapCard gap={gap({ ambition: [] })} />);
    expect(container.textContent).not.toContain("목표의 야심도");
  });
});
