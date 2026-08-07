import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { apiGet } from "./client";

// 2.6 ScreeningOut 스키마와 1:1. null 계약이 타입에 그대로 드러난다.
export interface ScreeningRow {
  corp_code: string;
  corp_name: string | null;
  market: string | null;
  sector: string | null;
  as_of: string;
  roe: number | null; // 핵심지표(AC3) — null=지표 없음
  pbr: number | null;
  // 총주주환원율(%, 최신 지표) — '매입만·소각 0' 필터(2026-08-04)의 짝.
  // null=산출 불가(분자 미상 포함 — 0%로 표시 금지)
  total_return_ratio: number | null;
  // 소각 기준 환원율(0028) = (배당+소각액)/순이익. 매입 기준과의 차이가 곧
  // '매입만 한 기업' 신호. null=소각액 미상(혼합 행 등 — 0%로 표시 금지)
  retired_return_ratio: number | null;
  execution_score: number | null;
  score_basis: string | null; // 채점 근거(5-1) — 가중치 기반이 종목마다 다름
  washing_flag: boolean | null; // true=워싱의심 / false=근거없음 / null=판단불가
  buyback_status: string | null;
  buyback_executed: boolean | null;
  // 소각 **시점**(0022, P1-4): in_period/outside_period(계획 기간 기준) ·
  // after_disclosure/before_disclosure(공시일 기준) · same_year_unknown(판정 불가) · null.
  buyback_timing: string | null;
  mna_target_score: number | null; // null=산출불가(엄격 게이팅)
  population_basis: string | null; // sector:{KSIC} / market_fallback / market
  // 공시 불투명도(washing_flag 대체) — 미공시 목표 축 수의 peer 백분위.
  // null=순위 불가(계획 미공시·본문 4축 전무·peer 부족). 0이나 "최투명"으로 표시 금지.
  opacity_rank: number | null;
  opacity_count: number | null; // 미공시 축 수(0~4). 본문 전무(4)는 순위에서 제외돼 실질 0~3
  opacity_basis: string | null; // sector:{KSIC} / market_fallback / market
  // 근거 공시의 본문 신호(0018): axis_targets/other_metric/refiling/no_targets.
  // '순위 불가'가 부실 공시인지 "타 지표로 공시"(우리 자에 눈금 없음)인지 구분용.
  plan_body_signal: string | null;
  // 순위 불가의 사유(6.4) — undisclosed | unreadable | unstated | null
  unrankable_reason: string | null;
  // 목표의 야심도(P1-7) — 공시한 축 중 **자기 과거 대비 가장 낮은 격차**(%p).
  // 음수 = 하던 것보다 낮게 약속. null = 비교할 과거 실적 없음(격차 0이 **아니다**).
  // 상세 ambition의 own_gap과 같은 정의(plan_own_gap 뷰가 단일 정의처).
  lowest_own_gap: number | null;
  has_valueup_score: boolean; // false=엔진 미집계(산출불가와 구분)
  has_mna_score: boolean;
  has_opacity_score: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

export type ScoreMode = "valueup" | "mna";

export interface ScreeningParams {
  corp_code?: string; // 3.4 상세화면 단건 조회용
  market?: string;
  sector?: string;
  min_execution_score?: number;
  max_execution_score?: number;
  min_mna_score?: number;
  max_mna_score?: number;
  // 지표 범위 필터(AC2, 3.3 리뷰 반영)
  min_roe?: number;
  max_pbr?: number;
  max_ev_ebit?: number;
  max_debt_ratio?: number;
  // 시총구간(KRW 원)
  min_market_cap?: number;
  max_market_cap?: number;
  // 불투명도 범위(AC2) — 구 washing_only 대체
  min_opacity_rank?: number;
  max_opacity_rank?: number;
  // 자기 과거 대비 목표 격차 상한(%p) — 0이면 "하던 것보다 낮은 목표"만.
  max_own_gap?: number;
  buyback_executed?: boolean;
  // '매입만·소각 0' 필터(2026-08-04): status 정확일치 + 총환원율 하한 조합
  buyback_status?: string;
  min_total_return?: number;
  sort?: string; // field / -field
  page?: number;
  size?: number;
}

export function useScreening(params: ScreeningParams) {
  return useQuery({
    queryKey: ["screening", params],
    queryFn: () => apiGet<Page<ScreeningRow>>("/screening", params as Record<string, unknown>),
    placeholderData: keepPreviousData, // 필터 변경 시 깜빡임 방지
  });
}

// 상세화면 헤더용 단건 조회(3.4) — 목록 API를 corp_code 필터+size=1로 재사용(신규
// 엔드포인트 회피). 종목이 스코어 미보유일 수 있어 total=0(빈 결과)이 정상 케이스.
export function useScreeningDetail(corpCode: string | undefined) {
  return useQuery({
    queryKey: ["screening-detail", corpCode],
    queryFn: () => apiGet<Page<ScreeningRow>>("/screening", { corp_code: corpCode, size: 1 }),
    enabled: !!corpCode,
    select: (page) => page.items[0] ?? null,
  });
}
