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
// as_of는 헤더(/screening)의 기준일로 체이닝(3.4 리뷰 High — 카드별로 서로 다른 최신일을
// 섞어 한 화면에 합성하지 않기 위해 화면 전체가 header.as_of 단일 기준일로 수렴).
// 그 기준일에 엔진이 안 돌았으면 빈 결과 = "미집계"가 그 기준일에 대한 정확한 표현.
export function useGapDetail(corpCode: string | undefined, asOf: string | undefined) {
  return useQuery({
    queryKey: ["gap-detail", corpCode, asOf],
    queryFn: () =>
      apiGet<Page<GapDetail>>("/valueup/gap-analysis", { corp_code: corpCode, as_of: asOf, size: 1 }),
    enabled: !!corpCode && !!asOf,
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

// 3.4: /mna/ranking을 corp_code 필터+size=1로 재사용. as_of 체이닝은 useGapDetail과 동일.
export function useMnaDetail(corpCode: string | undefined, asOf: string | undefined) {
  return useQuery({
    queryKey: ["mna-detail", corpCode, asOf],
    queryFn: () =>
      apiGet<Page<MnaDetail>>("/mna/ranking", { corp_code: corpCode, as_of: asOf, size: 1 }),
    enabled: !!corpCode && !!asOf,
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
