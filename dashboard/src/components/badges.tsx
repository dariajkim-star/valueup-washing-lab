import type { ScreeningRow } from "../api/screening";

// 3.2 Figma 범례(node 11:2)의 null 시각 언어를 그대로 구현.
// 원칙: null을 빈칸·0·"아니오"로 뭉개지 않는다(2.4~2.6 API 계약 승계).

function Pill({ text, bg, fg, dashed }: { text: string; bg?: string; fg: string; dashed?: boolean }) {
  return (
    <span
      className="inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold"
      style={{
        background: bg ?? "transparent",
        color: fg,
        border: dashed ? "1px dashed #d1d5db" : undefined,
      }}
    >
      {text}
    </span>
  );
}

export function WashingBadge({ flag }: { flag: boolean | null }) {
  if (flag === true) return <Pill text="⚠ 워싱 의심" bg="#fee4e2" fg="#b42318" />;
  if (flag === false) return <span className="text-xs text-gray-400">근거 없음</span>;
  return <Pill text="판단 불가" fg="#6b7280" dashed />; // null
}

function scoreColor(v: number): string {
  if (v >= 70) return "#0e9f6e";
  if (v >= 50) return "#65a30d";
  if (v >= 30) return "#ca8a04";
  return "#dc2626";
}

export function ValueUpCell({ row }: { row: ScreeningRow }) {
  if (!row.has_valueup_score) return <Pill text="미집계" fg="#9ca3af" dashed />;
  if (row.execution_score === null) return <span className="text-xs text-gray-400">—</span>;
  return (
    <span className="text-[15px] font-bold" style={{ color: scoreColor(row.execution_score) }}>
      {row.execution_score.toFixed(0)}
    </span>
  );
}

// 은행·보험 등 M&A 스코어가 구조적으로 산출 불가한 업종(KSIC 64~66 금융·보험).
// 리스트(MnaCell)와 상세(MnaBreakdown)가 같은 판정을 공유(3.4 리뷰 Med — 표현 불일치 방지).
export function isUnsupportedSector(sector: string | null): boolean {
  if (!sector) return false;
  const p = sector.slice(0, 2);
  return p === "64" || p === "65" || p === "66";
}

export function MnaCell({ row }: { row: ScreeningRow }) {
  if (!row.has_mna_score) return <Pill text="미집계" fg="#9ca3af" dashed />;
  if (row.mna_target_score === null) {
    if (isUnsupportedSector(row.sector)) {
      return (
        <div className="flex flex-col items-end gap-0.5">
          <Pill text="미지원 업종" bg="#f3f4f6" fg="#6b7280" />
          <span className="text-[9px] text-gray-400">은행·보험</span>
        </div>
      );
    }
    return (
      <div className="flex flex-col items-end gap-0.5">
        <span className="text-[15px] font-bold text-gray-400">—</span>
        <span className="text-[10px] text-gray-400">산출 불가</span>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-end gap-0.5">
      <span className="text-[15px] font-bold" style={{ color: scoreColor(row.mna_target_score) }}>
        {row.mna_target_score.toFixed(1)}
      </span>
      <PopulationBasisChip basis={row.population_basis} />
    </div>
  );
}

export function PopulationBasisChip({ basis }: { basis: string | null }) {
  if (!basis) return null;
  let label = "전체시장";
  if (basis.startsWith("sector:")) label = `업종 내 (KSIC ${basis.slice(7)})`;
  else if (basis === "market_fallback") label = "전체시장 폴백";
  return <span className="text-[9px] text-gray-400">{label}</span>;
}

export function MarketPill({ market }: { market: string | null }) {
  if (!market) return <span className="text-xs text-gray-400">—</span>;
  const kospi = market === "KOSPI";
  return <Pill text={market} bg={kospi ? "#eff6ff" : "#f5f3ff"} fg={kospi ? "#1d4ed8" : "#6d28d9"} />;
}
