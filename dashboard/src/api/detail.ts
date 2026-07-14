import { useQuery } from "@tanstack/react-query";
import { apiGet } from "./client";
import type { Page } from "./screening";

// 2.4 GapAnalysisOut 스키마와 1:1.
export interface GapDetail {
  corp_code: string;
  corp_name: string | null;
  market: string | null;
  as_of: string;
  target_roe: number | null;
  actual_roe: number | null;
  roe_gap: number | null;
  achievement_rate: number | null;
  progress_rate: number | null;
  execution_score: number | null;
  washing_flag: boolean | null;
  buyback_status: string | null;
}

// 3.4: /valueup/gap-analysis를 corp_code 필터+size=1로 재사용(신규 엔드포인트 회피).
export function useGapDetail(corpCode: string | undefined) {
  return useQuery({
    queryKey: ["gap-detail", corpCode],
    queryFn: () => apiGet<Page<GapDetail>>("/valueup/gap-analysis", { corp_code: corpCode, size: 1 }),
    enabled: !!corpCode,
    select: (page) => page.items[0] ?? null,
  });
}

// 2.5 MnaRankingOut 스키마와 1:1.
export interface MnaDetail {
  corp_code: string;
  corp_name: string | null;
  market: string | null;
  sector: string | null;
  as_of: string;
  mna_target_score: number | null;
  valuation_score: number | null;
  capacity_score: number | null;
  ownership_score: number | null;
  macro_score: number | null;
  population_basis: string | null;
}

// 3.4: /mna/ranking을 corp_code 필터+size=1로 재사용.
export function useMnaDetail(corpCode: string | undefined) {
  return useQuery({
    queryKey: ["mna-detail", corpCode],
    queryFn: () => apiGet<Page<MnaDetail>>("/mna/ranking", { corp_code: corpCode, size: 1 }),
    enabled: !!corpCode,
    select: (page) => page.items[0] ?? null,
  });
}

// 1.7 MetricOut 스키마와 1:1(분기별 시계열, 이미 존재하는 단건조회 경로 — 변경 없음).
export interface MetricPoint {
  corp_code: string;
  corp_name: string | null;
  market: string | null;
  sector: string | null;
  year: number;
  quarter: number;
  roe: number | null;
  roa: number | null;
  pbr: number | null;
  per: number | null;
  ev_ebitda: number | null;
  debt_ratio: number | null;
  payout_ratio: number | null;
  net_cash: number | null;
  ebitda_margin: number | null;
  yoy_revenue_growth: number | null;
  yoy_income_growth: number | null;
}

export function useMetricsByCorp(corpCode: string | undefined) {
  return useQuery({
    queryKey: ["metrics-by-corp", corpCode],
    queryFn: () => apiGet<MetricPoint[]>(`/metrics/${corpCode}`),
    enabled: !!corpCode,
  });
}
