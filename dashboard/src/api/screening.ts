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
  execution_score: number | null;
  score_basis: string | null; // 채점 근거(5-1) — 가중치 기반이 종목마다 다름
  washing_flag: boolean | null; // true=워싱의심 / false=근거없음 / null=판단불가
  buyback_status: string | null;
  buyback_executed: boolean | null;
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
  max_ev_ebitda?: number;
  max_debt_ratio?: number;
  // 시총구간(KRW 원)
  min_market_cap?: number;
  max_market_cap?: number;
  // 불투명도 범위(AC2) — 구 washing_only 대체
  min_opacity_rank?: number;
  max_opacity_rank?: number;
  buyback_executed?: boolean;
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
