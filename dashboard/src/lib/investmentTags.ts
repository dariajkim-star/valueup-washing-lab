import type { GapDetail } from "../api/detail";
import type { MnaDetail } from "../api/detail";
import type { MetricPoint } from "../api/detail";

export interface Tag {
  label: string;
  group: "valueup" | "mna";
}

// AC5 자동 태깅 — 순수 함수(입력 데이터만으로 판정, 부수효과 없음). 근거 지표가 null이면
// 태그를 만들지 않는다(추측으로 태그 생성 금지 — API가 지킨 null 정직성을 화면 마지막
// 단계에서 깨지 않기 위함). 임계치는 이 스토리의 표시 로직 상수(config.py의 스코어링
// 가중치와는 별개 — 스코어 산식이 아니라 "셀링포인트로 부를 만한가"의 프론트 판단).
const VALUEUP_HIGH_ROE = 10; // %
const VALUEUP_LOW_PBR = 1.0; // x
const MNA_STRONG_FACTOR = 0.7; // 0~1 스케일 상위 30% 근사

export function valueupTags(latestMetric: MetricPoint | undefined, gap: GapDetail | null): Tag[] {
  const tags: Tag[] = [];
  if (latestMetric?.roe !== undefined && latestMetric?.roe !== null && latestMetric.roe >= VALUEUP_HIGH_ROE) {
    tags.push({ label: `고ROE (${latestMetric.roe.toFixed(1)}%)`, group: "valueup" });
  }
  if (latestMetric?.pbr !== undefined && latestMetric?.pbr !== null && latestMetric.pbr <= VALUEUP_LOW_PBR) {
    tags.push({ label: `저PBR (${latestMetric.pbr.toFixed(2)}x)`, group: "valueup" });
  }
  // buyback_status가 null(엔진 미실행/미보유)이면 태그 없음 — "retired"일 때만
  if (gap?.buyback_status === "retired") {
    tags.push({ label: "자사주 실이행 (소각 확인)", group: "valueup" });
  }
  return tags;
}

export function mnaTags(mna: MnaDetail | null): Tag[] {
  if (!mna) return [];
  const tags: Tag[] = [];
  // capacity_score는 부채비율뿐 아니라 순현금·마진도 섞인 복합 지표라 "저부채"는 근사
  // 라벨(2.3 산식 자체가 그렇게 설계됨 — 3.4 스토리 스코프의 기록된 한계).
  if (mna.valuation_score !== null && mna.valuation_score >= MNA_STRONG_FACTOR) {
    tags.push({ label: "저평가", group: "mna" });
  }
  if (mna.capacity_score !== null && mna.capacity_score >= MNA_STRONG_FACTOR) {
    tags.push({ label: "저부채", group: "mna" });
  }
  if (mna.ownership_score !== null && mna.ownership_score >= MNA_STRONG_FACTOR) {
    tags.push({ label: "낮은 지분율", group: "mna" });
  }
  return tags;
}
