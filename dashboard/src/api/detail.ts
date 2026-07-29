import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { apiGet, apiPost } from "./client";
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
  score_basis: string | null; // 채점 근거(5-1)
  washing_flag: boolean | null;
  buyback_status: string | null;
  // 출처(0015): 이 점수가 어느 공시에서 나왔는가. rcept_no가 null이면 컬럼 신설 이전
  // 적재분이라 DART 원문으로 갈 수 없다 — 재수집해야 채워진다.
  plan_disclosure_date: string | null;
  plan_rcept_no: string | null;
  // 근거 공시가 최신이 아닌가(최신 공시에 목표가 없어 이전 공시로 폴백).
  plan_is_fallback: boolean;
  plan_newest_disclosure_date: string | null;
  // 본문이 왜 우리 축을 못 채웠는가: axis_targets / other_metric / refiling / no_targets
  plan_body_signal: string | null;
}

// POST /valueup/refresh/{corp_code} 응답 — 단계별 보고(성공/실패 한 값으로 뭉치지 않는다).
export interface RefreshResult {
  corp_code: string;
  as_of: string;
  plans_ingested: number;
  ingest_ok: boolean;
  ingest_error: string | null;
  scored: boolean;
  score_error: string | null;
  opacity_reranked: boolean;
  opacity_error: string | null;
  warnings: string[];
  complete: boolean;
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

// 단건 새로고침(DART 재수집 + 재채점). 성공 시 캐시를 통째로 무효화하는 이유:
// 이 호출은 **이 종목만** 바꾸지 않는다 — opacity_rank는 모집단 백분위라 전 종목이
// 재계산되므로, 목록·다른 종목 상세도 낡은다. 좁게 무효화하면 화면마다 다른 세대가 섞인다.
export function useRefreshCompany(corpCode: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<RefreshResult>(`/valueup/refresh/${corpCode}`),
    onSuccess: () => qc.invalidateQueries(),
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
