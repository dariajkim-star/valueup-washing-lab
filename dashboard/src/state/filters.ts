import { create } from "zustand";
import type { ScoreMode, ScreeningParams } from "../api/screening";

// UI 상태(필터·스코어 모드·정렬·페이지) — 서버 상태(TanStack Query)와 분리(AD-11).

const DEFAULT_SORT: Record<ScoreMode, string> = {
  valueup: "execution_score", // 이행 나쁜 순(오름차순) = 워싱 방향
  mna: "-mna_target_score", // 인수 매력 높은 순(내림차순)
};

interface FilterState {
  scoreMode: ScoreMode;
  market?: string; // "KOSPI" | "KOSDAQ" | undefined(전체)
  sector?: string; // KSIC prefix
  minExecutionScore?: number;
  maxExecutionScore?: number;
  minMnaScore?: number;
  maxMnaScore?: number;
  washingOnly: boolean;
  buybackExecuted?: boolean;
  sort: string;
  page: number;
  size: number;
  setScoreMode: (m: ScoreMode) => void;
  setMarket: (m?: string) => void;
  setWashingOnly: (v: boolean) => void;
  setSort: (s: string) => void;
  setPage: (p: number) => void;
  patch: (p: Partial<FilterState>) => void;
}

export const useFilters = create<FilterState>((set) => ({
  scoreMode: "valueup",
  washingOnly: false,
  sort: DEFAULT_SORT.valueup,
  page: 1,
  size: 20,
  // 스코어 모드 전환 시 기본 정렬을 그 모드의 관점으로 스왑 + 1페이지로(6번 AC)
  setScoreMode: (m) => set({ scoreMode: m, sort: DEFAULT_SORT[m], page: 1 }),
  setMarket: (market) => set({ market, page: 1 }),
  setWashingOnly: (washingOnly) => set({ washingOnly, page: 1 }),
  setSort: (sort) => set({ sort, page: 1 }),
  setPage: (page) => set({ page }),
  patch: (p) => set({ ...p, page: 1 }),
}));

// 스토어 상태 → API 파라미터(미선택은 client.ts가 걸러냄)
export function toParams(s: FilterState): ScreeningParams {
  return {
    market: s.market,
    sector: s.sector,
    min_execution_score: s.minExecutionScore,
    max_execution_score: s.maxExecutionScore,
    min_mna_score: s.minMnaScore,
    max_mna_score: s.maxMnaScore,
    washing_only: s.washingOnly || undefined,
    buyback_executed: s.buybackExecuted,
    sort: s.sort,
    page: s.page,
    size: s.size,
  };
}

export { DEFAULT_SORT };
