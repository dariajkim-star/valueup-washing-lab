import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

// vitest globals 미사용 시 testing-library 자동 cleanup이 비활성 — 명시적 cleanup
afterEach(cleanup);
import { MnaCell, ValueUpCell, WashingBadge, ScoreBasisChip } from "./badges";
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
    execution_score: null,
    score_basis: null,
    washing_flag: null,
    buyback_status: null,
    buyback_executed: null,
    mna_target_score: null,
    population_basis: null,
    has_valueup_score: true,
    has_mna_score: true,
    ...partial,
  };
}

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

describe("MnaCell — 상태 우선순위: 미집계 > 미지원업종 > 산출불가 > 값", () => {
  it("has_mna_score=false가 최우선(금융주라도 미집계)", () => {
    render(<MnaCell row={row({ has_mna_score: false, sector: "64110" })} />);
    expect(screen.getByText("미집계")).toBeTruthy();
    expect(screen.queryByText("미지원 업종")).toBeNull();
  });
  it("KSIC 64~66 + null → 미지원 업종(개별 산출불가가 아니라 업종 안내)", () => {
    render(<MnaCell row={row({ sector: "65121", mna_target_score: null })} />);
    expect(screen.getByText("미지원 업종")).toBeTruthy();
  });
  it("비금융 + null → 산출 불가(0점/최하위 금지)", () => {
    render(<MnaCell row={row({ sector: "26100", mna_target_score: null })} />);
    expect(screen.getByText("산출 불가")).toBeTruthy();
    expect(screen.queryByText("0.0")).toBeNull();
  });
  it("값 있으면 점수 + population_basis chip", () => {
    render(<MnaCell row={row({ mna_target_score: 71.1, population_basis: "market_fallback" })} />);
    expect(screen.getByText("71.1")).toBeTruthy();
    expect(screen.getByText("전체시장 폴백")).toBeTruthy();
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
