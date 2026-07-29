import { create } from "zustand";
import type { ScoreMode, ScreeningParams } from "../api/screening";

// UI 상태(필터·스코어 모드·정렬·페이지) — 서버 상태(TanStack Query)와 분리(AD-11).

// [2026-07-28 파티 결정] Value-up 모드 기본 정렬을 불투명도 내림차순으로 전환.
// 이 도구의 목적은 "잘 이행한 기업 찾기"가 아니라 **"공시가 빈약한 기업 걸러내기"**다
// (daria painpoint). execution_score 정렬은 그 목적과 어긋났다 — 실측상 상위 7칸이 전부
// 단일 이진 축(자사주만 약속·이행) 100점이었고, 세 약속을 다 지킨 기아가 8등이었다.
const DEFAULT_SORT: Record<ScoreMode, string> = {
  valueup: "-opacity_rank", // 불투명 높은 순 = 걸러낼 후보 우선
  mna: "-mna_target_score", // 인수 매력 높은 순(내림차순)
};

// [2026-07-28 결정] 불투명도 임계 소유권 = **화면 다이얼**. config 고정이 아니다.
// 근거: ① 모집단이 20개(is_unrankable 제외 후)라 어떤 고정 임계도 자의적이다 —
// 0.7이 6개를 뽑든 4개를 뽑든 그 경계에 실질적 의미가 없다. ② 이 도구는 판정기가 아니라
// 애널리스트의 탐색 도구다(daria painpoint: "걸러낼 후보를 좁혀가며 본다").
// ③ `/screening`이 이미 min_opacity_rank를 임의값으로 받으므로 백엔드 변경이 0이다.
// 아래 값은 다이얼의 **기본 위치**일 뿐, 잠긴 정의가 아니다.
export const DEFAULT_OPAQUE_MIN_RANK = 0.7;

// 시총구간 버킷(KRW 원, 백엔드 비교는 포함(>=,<=)이라 max는 -1로 잘라 상호 배타 보장):
// 대형 = 10조 이상 / 중형 = 1조 이상 10조 미만 / 소형 = 1조 미만 (재리뷰 #2 — 경계 중복 제거)
export type McapBucket = "all" | "large" | "mid" | "small";
const TRILLION = 1_000_000_000_000;
export const MCAP_BOUNDS: Record<McapBucket, { min?: number; max?: number }> = {
  all: {},
  large: { min: 10 * TRILLION },
  mid: { min: 1 * TRILLION, max: 10 * TRILLION - 1 },
  small: { max: 1 * TRILLION - 1 },
};

export interface FilterState {
  scoreMode: ScoreMode;
  market?: string; // "KOSPI" | "KOSDAQ" | undefined(전체)
  sector?: string; // KSIC prefix
  mcapBucket: McapBucket;
  minRoe?: number; // %
  maxPbr?: number; // x
  maxEvEbitda?: number; // x
  maxDebtRatio?: number; // %
  // 불투명 상위만 보기(구 washingOnly)의 임계값 — undefined = 필터 꺼짐.
  // boolean+상수가 아니라 값 하나로 둔다: 임계가 화면 소유가 된 이상 "켜짐 여부"는
  // "값이 있는가"와 같은 말이고, 둘로 나누면 토글이 켜졌는데 임계가 다른 상태가 생긴다.
  opaqueMinRank?: number; // 0~1
  buybackExecuted?: boolean;
  sort: string;
  page: number;
  size: number;
  setScoreMode: (m: ScoreMode) => void;
  setMarket: (m?: string) => void;
  setSector: (s?: string) => void;
  setMcapBucket: (b: McapBucket) => void;
  setOpaqueMinRank: (v?: number) => void;
  setSort: (s: string) => void;
  setPage: (p: number) => void;
  patch: (p: Partial<FilterState>) => void; // 필터류 일괄 갱신(page 1 리셋)
}

export const useFilters = create<FilterState>((set) => ({
  scoreMode: "valueup",
  mcapBucket: "all",
  opaqueMinRank: undefined,
  sort: DEFAULT_SORT.valueup,
  page: 1,
  size: 20,
  // 스코어 모드 전환 시 기본 정렬을 그 모드의 관점으로 스왑 + 1페이지로(AC6)
  setScoreMode: (m) => set({ scoreMode: m, sort: DEFAULT_SORT[m], page: 1 }),
  setMarket: (market) => set({ market, page: 1 }),
  setSector: (sector) => set({ sector, page: 1 }),
  setMcapBucket: (mcapBucket) => set({ mcapBucket, page: 1 }),
  setOpaqueMinRank: (opaqueMinRank) => set({ opaqueMinRank, page: 1 }),
  setSort: (sort) => set({ sort, page: 1 }),
  setPage: (page) => set({ page }),
  patch: (p) => set({ ...p, page: 1 }),
}));

// 스토어 상태 → API 파라미터(미선택은 client.ts가 걸러냄)
export function toParams(s: FilterState): ScreeningParams {
  const mcap = MCAP_BOUNDS[s.mcapBucket];
  return {
    market: s.market,
    sector: s.sector,
    min_roe: s.minRoe,
    max_pbr: s.maxPbr,
    max_ev_ebitda: s.maxEvEbitda,
    max_debt_ratio: s.maxDebtRatio,
    min_market_cap: mcap.min,
    max_market_cap: mcap.max,
    min_opacity_rank: s.opaqueMinRank,
    buyback_executed: s.buybackExecuted,
    sort: s.sort,
    page: s.page,
    size: s.size,
  };
}

export { DEFAULT_SORT };
