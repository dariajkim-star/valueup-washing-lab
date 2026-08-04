import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

// vitest globals 미사용 시 testing-library 자동 cleanup이 비활성 — 명시적 cleanup
afterEach(cleanup);
import {
  BuybackRetiredBadge,
  MnaCell,
  OpacityCell,
  ValueUpCell,
  WashingBadge,
  ScoreBasisChip,
  AmbitionBadge,
  PurchasedOnlyBadge,
} from "./badges";
import type { ScreeningRow } from "../api/screening";

// null 시각 언어(3.2 범례)의 상태 우선순위 검증 — 금칙: 빈칸·0·"아니오"로 뭉개기.

function row(partial: Partial<ScreeningRow>): ScreeningRow {
  return {
    corp_code: "00000000",
    corp_name: "테스트",
    market: "KOSPI",
    sector: "26100",
    as_of: "2026-07-13",
    roe: null,
    pbr: null,
    total_return_ratio: null,
    retired_return_ratio: null,
    execution_score: null,
    score_basis: null,
    washing_flag: null,
    buyback_status: null,
    buyback_executed: null,
    mna_target_score: null,
    population_basis: null,
    opacity_rank: null,
    opacity_count: null,
    opacity_basis: null,
    plan_body_signal: null,
    lowest_own_gap: null,
    buyback_timing: null,
    has_valueup_score: true,
    has_mna_score: true,
    has_opacity_score: true,
    ...partial,
  };
}

describe("[AC3] BuybackRetiredBadge — 사실만, 판정 아님", () => {
  it("retired → '최근 소각' 배지", () => {
    render(<BuybackRetiredBadge status="retired" />);
    expect(screen.getByText("최근 소각")).toBeTruthy();
  });

  it("라벨은 계획 '이행'을 주장하지 않는다", () => {
    // 실측: retired 16종목 중 소각이 계획 기간 안에 든 건 5종목뿐(시작 전 3·종료 후 1·
    // 미상 7). buyback_status는 계획 기간으로 걸러지지 않으므로(latest_financial_buyback),
    // "이행"이라는 단어는 데이터에 없는 인과를 주장한다. 되돌림 방지용 회귀 테스트.
    const { container } = render(<BuybackRetiredBadge status="retired" />);
    expect(container.textContent).not.toContain("이행");
    expect(container.querySelector("[title]")?.getAttribute("title")).toContain("계획 기간과 무관");
  });
  it("purchased_only·none은 배지 없음 — '안 했다'를 강조하면 판정이 된다", () => {
    for (const s of ["purchased_only", "none"]) {
      const { container } = render(<BuybackRetiredBadge status={s} />);
      expect(container.textContent).toBe("");
      cleanup();
    }
  });
  it("unknown·null은 배지 없음 — 못 읽은 걸 벌하지 않는다", () => {
    for (const s of ["unknown", null]) {
      const { container } = render(<BuybackRetiredBadge status={s} />);
      expect(container.textContent).toBe("");
      cleanup();
    }
  });
});

describe("WashingBadge — 3상태", () => {
  it("true → 워싱 의심", () => {
    render(<WashingBadge flag={true} />);
    expect(screen.getByText(/워싱 의심/)).toBeTruthy();
  });
  it("false → 근거 없음(강조 없음)", () => {
    render(<WashingBadge flag={false} />);
    expect(screen.getByText("근거 없음")).toBeTruthy();
  });
  it('null → "판단 불가"(빈칸/"아니오" 금지)', () => {
    render(<WashingBadge flag={null} />);
    expect(screen.getByText("판단 불가")).toBeTruthy();
    expect(screen.queryByText("아니오")).toBeNull();
  });
});

describe("ValueUpCell — 미집계 vs 산출불가 vs 값", () => {
  it("has_valueup_score=false → 미집계(점수 null이어도 산출불가 아님)", () => {
    render(<ValueUpCell row={row({ has_valueup_score: false, execution_score: null })} />);
    expect(screen.getByText("미집계")).toBeTruthy();
  });
  it("row 있음 + score null → — (0으로 표시 금지)", () => {
    render(<ValueUpCell row={row({ execution_score: null })} />);
    expect(screen.getByText("—")).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
  });
  it("값 있으면 숫자 표시", () => {
    render(<ValueUpCell row={row({ execution_score: 85 })} />);
    expect(screen.getByText("85")).toBeTruthy();
  });
});

describe("MnaCell — 상태 우선순위: 미집계 > 산식미적용 > 산출불가 > 값", () => {
  it("has_mna_score=false가 최우선(금융주라도 미집계)", () => {
    render(<MnaCell row={row({ has_mna_score: false, sector: "64110" })} />);
    expect(screen.getByText("미집계")).toBeTruthy();
    expect(screen.queryByText("산식 미적용")).toBeNull();
  });
  it("보험(65xxx) + null → 산식 미적용(EBITDA 개념이 성립하지 않는 업종)", () => {
    render(<MnaCell row={row({ sector: "65121", mna_target_score: null })} />);
    expect(screen.getByText("산식 미적용")).toBeTruthy();
  });
  it("은행(641xx) + null → 산식 미적용", () => {
    render(<MnaCell row={row({ sector: "64121", mna_target_score: null })} />);
    expect(screen.getByText("산식 미적용")).toBeTruthy();
  });
  // [정정 2026-08-03] 64 대분류는 은행과 **지주회사**를 한 칸에 넣는다. 그 탓에 화면이
  // LG·롯데지주에게 "은행·보험"이라 말하고 있었다. 실측: 지주 64992는 19/38이 점수를 받는다.
  it("지주회사(64992) + null → 산출 불가. 은행·보험이라 말하지 않는다", () => {
    render(<MnaCell row={row({ sector: "64992", mna_target_score: null })} />);
    expect(screen.getByText("산출 불가")).toBeTruthy();
    expect(screen.queryByText("산식 미적용")).toBeNull();
    expect(screen.queryByText("은행·보험")).toBeNull();
  });
  it("증권(66121) + null → 산출 불가(실제로 점수를 받는 종목이 있다)", () => {
    render(<MnaCell row={row({ sector: "66121", mna_target_score: null })} />);
    expect(screen.getByText("산출 불가")).toBeTruthy();
  });
  it("표본이 1~2개뿐인 소분류는 0건이어도 미적용으로 선언하지 않는다(small-N)", () => {
    render(<MnaCell row={row({ sector: "64913", mna_target_score: null })} />);
    expect(screen.getByText("산출 불가")).toBeTruthy();
  });
  it("비금융 + null → 산출 불가(0점/최하위 금지)", () => {
    render(<MnaCell row={row({ sector: "26100", mna_target_score: null })} />);
    expect(screen.getByText("산출 불가")).toBeTruthy();
    expect(screen.queryByText("0.0")).toBeNull();
  });
  it("값 있으면 점수 + population_basis chip", () => {
    render(<MnaCell row={row({ mna_target_score: 71.1, population_basis: "market_fallback" })} />);
    // [파티 결정 2026-07-29] "전체시장 폴백" → "시장 전체 비교"(전건이 fallback인 현실을
    // 일시 강등처럼 읽히는 "폴백" 대신 지금 사실인 문장으로).
    expect(screen.getByText("71.1")).toBeTruthy();
    expect(screen.getByText("시장 전체 비교")).toBeTruthy();
  });
  it("sector null(미분류) + null → 산출 불가(미지원으로 오판하지 않음)", () => {
    render(<MnaCell row={row({ sector: null, mna_target_score: null })} />);
    expect(screen.getByText("산출 불가")).toBeTruthy();
  });
});

// ── 5-1: score_basis 시각 언어 ──

describe("ScoreBasisChip", () => {
  it("다항목은 근거를 나열한다", () => {
    render(<ScoreBasisChip basis="roe+buyback+payout" />);
    expect(screen.getByText("ROE·자사주·배당성향")).toBeTruthy();
  });

  it("주주환원율은 배당성향과 다른 라벨로 표시된다", () => {
    render(<ScoreBasisChip basis="buyback+total_return" />);
    expect(screen.getByText("자사주·주주환원")).toBeTruthy();
  });

  it("단일 항목은 '~만'으로 구분 표기한다", () => {
    // 자사주 단독은 이진값이라 0/100뿐 — 다항목 100점과 같아 보이면 안 된다
    render(<ScoreBasisChip basis="buyback" />);
    expect(screen.getByText("자사주만")).toBeTruthy();
  });

  it("basis가 없으면 아무것도 그리지 않는다", () => {
    const { container } = render(<ScoreBasisChip basis={null} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("ValueUpCell + score_basis", () => {
  it("점수와 근거를 함께 보여준다", () => {
    render(<ValueUpCell row={row({ execution_score: 100, score_basis: "roe+buyback+payout" })} />);
    expect(screen.getByText("100")).toBeTruthy();
    expect(screen.getByText("ROE·자사주·배당성향")).toBeTruthy();
  });

  it("같은 100점이라도 근거가 다르면 다르게 읽힌다(회귀 방지)", () => {
    // 실데이터: 기아 100(roe+buyback+payout) vs 삼성전자 100(buyback 단독)
    const { unmount } = render(<ValueUpCell row={row({ execution_score: 100, score_basis: "buyback" })} />);
    expect(screen.getByText("자사주만")).toBeTruthy();
    unmount();
    render(<ValueUpCell row={row({ execution_score: 100, score_basis: "roe+buyback+payout" })} />);
    expect(screen.queryByText("자사주만")).toBeNull();
  });

  it("점수 null은 빈칸이 아니라 '판단 불가'로 표시한다", () => {
    render(<ValueUpCell row={row({ execution_score: null })} />);
    expect(screen.getByText("판단 불가")).toBeTruthy();
  });
});

describe("OpacityCell — 불투명도(washing_flag 대체)", () => {
  it("순위 있음 → 백분위 정수 + 미공시 축 수", () => {
    render(<OpacityCell row={row({ opacity_rank: 0.89, opacity_count: 3 })} />);
    expect(screen.getByText("89")).toBeTruthy();
    expect(screen.getByText(/미공시 3축/)).toBeTruthy();
  });

  it('순위 불가 → "순위 불가"(0·최투명으로 표시 금지)', () => {
    // 계획 미공시이거나 본문 4축이 전부 비어 **읽을 수 없는** 공시.
    // 못 읽은 걸 벌하지도(1), 봐주지도(0) 않는다.
    render(<OpacityCell row={row({ has_opacity_score: false, opacity_rank: null })} />);
    expect(screen.getByText("순위 불가")).toBeTruthy();
    expect(screen.queryByText("0")).toBeNull();
    expect(screen.queryByText("100")).toBeNull();
  });

  it("has_opacity_score=true인데 rank null이어도 순위 불가로 (peer 부족)", () => {
    render(<OpacityCell row={row({ has_opacity_score: true, opacity_rank: null })} />);
    expect(screen.getByText("순위 불가")).toBeTruthy();
  });

  it('순위 불가 + other_metric → "타 지표로 공시"(부실 공시와 구분)', () => {
    // [파티 결정 2026-07-29] 회사는 명확히 약속했고(CapEx·매출·EBITDA) 우리 자에
    // 눈금이 없을 뿐 — "순위 불가" 한 마디로 묶으면 사실 표기가 판정이 된다.
    render(<OpacityCell row={row({
      has_opacity_score: false, opacity_rank: null, plan_body_signal: "other_metric",
    })} />);
    expect(screen.getByText("타 지표로 공시")).toBeTruthy();
    expect(screen.queryByText("순위 불가")).toBeNull();
  });

  it("순위 불가 + no_targets는 여전히 '순위 불가'", () => {
    render(<OpacityCell row={row({
      has_opacity_score: false, opacity_rank: null, plan_body_signal: "no_targets",
    })} />);
    expect(screen.getByText("순위 불가")).toBeTruthy();
  });

  it("최투명(0) → 0으로 표시하되 순위 불가와 구분된다", () => {
    render(<OpacityCell row={row({ opacity_rank: 0.03, opacity_count: 0 })} />);
    expect(screen.getByText("3")).toBeTruthy(); // 0.03 → 3
    expect(screen.queryByText("순위 불가")).toBeNull();
  });
});

describe("[2026-07-31 P1-4] 소각 배지 — 약속과의 시점 관계를 말한다", () => {
  it("계획 기간 내 소각만 초록(이행)으로 표시한다", () => {
    render(<BuybackRetiredBadge status="retired" timing="in_period" />);
    expect(screen.getByText("계획 기간 내 소각")).toBeTruthy();
  });

  it("공시 전 소각은 이행이 아니라고 말한다", () => {
    // 실측: retired 53건 중 30건이 공시 전 소각이다. "최근 소각" 하나로 뭉치면
    // 약속과 무관한 소각이 이행처럼 읽힌다.
    render(<BuybackRetiredBadge status="retired" timing="before_disclosure" />);
    const el = screen.getByText("공시 전 소각");
    expect(el).toBeTruthy();
    expect(el.getAttribute("title")).toContain("이 약속의 이행은 아니다");
  });

  it("계획 기간 밖 소각도 구분한다(기아 실측 형태)", () => {
    render(<BuybackRetiredBadge status="retired" timing="outside_period" />);
    expect(screen.getByText("계획 기간 밖 소각")).toBeTruthy();
  });

  it("같은 해는 판정하지 않는다 — 회색으로 '시점 미상'", () => {
    render(<BuybackRetiredBadge status="retired" timing="same_year_unknown" />);
    expect(screen.getByText("소각(시점 미상)")).toBeTruthy();
  });

  it("timing이 없는 구데이터는 종전 라벨로 남는다(회귀 방지)", () => {
    render(<BuybackRetiredBadge status="retired" timing={null} />);
    expect(screen.getByText("최근 소각")).toBeTruthy();
  });

  it("retired가 아니면 timing이 있어도 배지 없음", () => {
    const { container } = render(<BuybackRetiredBadge status="none" timing="in_period" />);
    expect(container.textContent).toBe("");
  });
});


// [P1-7 2026-08-03] 목표 야심도 배지.
// 실측 근거: 만점 70건 중 40건이 자기 과거보다 낮은 목표인데 목록에서 구분되지 않았다.
describe("AmbitionBadge", () => {
  it("자기 과거보다 낮은 목표면 격차를 그대로 보여준다", () => {
    render(<AmbitionBadge gap={-10.5} />);
    expect(screen.getByText(/과거보다 낮은 목표/)).toBeTruthy();
    expect(screen.getByText(/-10\.5%p/)).toBeTruthy();
  });

  it("등급으로 압축하지 않는다 — 격차 숫자가 화면에 남는다", () => {
    const { container } = render(<AmbitionBadge gap={-41.0} />);
    expect(container.textContent).toContain("-41.0%p");
    expect(container.textContent).not.toMatch(/낮음|하위|등급/);
  });

  it("과거보다 높게 약속했으면 배지가 없다", () => {
    const { container } = render(<AmbitionBadge gap={20.0} />);
    expect(container.textContent).toBe("");
  });

  it("격차 0은 '같은 목표'로 구분해 말한다 — 필터(≤0)에 걸린 이유가 보여야 한다", () => {
    const { container } = render(<AmbitionBadge gap={0} />);
    expect(container.textContent).toContain("과거와 같은 목표");
    expect(container.textContent).not.toContain("낮은");
  });

  it("null(비교할 과거 없음)은 배지를 띄우지 않는다 — 측정 불가는 판정이 아니다", () => {
    const { container } = render(<AmbitionBadge gap={null} />);
    expect(container.textContent).toBe("");
  });
});

// [2026-08-04] "매입만 · 소각 0" 배지 — 필터 문맥 한정 렌더.
// 상시 배지는 "안 했다" 판정에 가까워진다는 BuybackRetiredBadge 원칙은 유지하되,
// 사용자가 명시적으로 걸러 달라고 한 화면에서는 걸린 이유가 보여야 한다.
describe("PurchasedOnlyBadge", () => {
  it("필터 켜짐 + purchased_only면 렌더", () => {
    render(<PurchasedOnlyBadge status="purchased_only" filterOn={true} />);
    expect(screen.getByText("매입만 · 소각 0")).toBeTruthy();
  });

  it("필터가 꺼져 있으면 purchased_only여도 렌더하지 않는다(상시 판정 금지)", () => {
    const { container } = render(
      <PurchasedOnlyBadge status="purchased_only" filterOn={false} />,
    );
    expect(container.textContent).toBe("");
  });

  it("retired·null은 필터가 켜져도 렌더하지 않는다", () => {
    const r1 = render(<PurchasedOnlyBadge status="retired" filterOn={true} />);
    expect(r1.container.textContent).toBe("");
    const r2 = render(<PurchasedOnlyBadge status={null} filterOn={true} />);
    expect(r2.container.textContent).toBe("");
  });
});
