import type { MnaDetail } from "../../api/detail";
import { PopulationBasisChip } from "../badges";

// UX-DR3/UX-DR4 M&A 4요소 분해(3.2 시안 재현). null 계약은 리스트와 동일 —
// mna_target_score null=산출 불가, population_basis chip 재사용.
const FACTORS: Array<{ key: keyof MnaDetail; label: string; weight: string }> = [
  { key: "valuation_score", label: "저평가 (valuation)", weight: "가중 0.35" },
  { key: "capacity_score", label: "인수여력 (capacity)", weight: "가중 0.25" },
  { key: "ownership_score", label: "지배구조 (ownership)", weight: "가중 0.25" },
  { key: "macro_score", label: "매크로 (macro)", weight: "가중 0.15" },
];

function factorColor(v: number): string {
  if (v >= 0.7) return "#65a30d";
  if (v >= 0.4) return "#ca8a04";
  return "#dc2626";
}

export function MnaBreakdown({ mna }: { mna: MnaDetail | null }) {
  if (!mna) {
    return (
      <div className="rounded-xl border border-gray-100 bg-white p-5 text-sm text-gray-400">
        M&A 스코어 데이터가 없습니다(엔진 미집계)
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-100 bg-white p-5">
      <h3 className="mb-1 text-sm font-bold text-gray-900">M&A 4요소 분해</h3>
      <div className="mb-3">
        <PopulationBasisChip basis={mna.population_basis} />
      </div>
      {mna.mna_target_score === null && (
        <p className="mb-3 text-xs text-gray-400">총점 산출 불가 — 요소 지표 결측(0점/최하위 아님)</p>
      )}
      <div className="flex flex-col gap-3">
        {FACTORS.map((f) => {
          const v = mna[f.key] as number | null;
          return (
            <div key={f.key}>
              <div className="mb-1.5 flex items-center gap-2">
                <span className="flex-1 text-xs font-semibold text-gray-700">{f.label}</span>
                <span className="text-[9px] text-gray-400">{f.weight}</span>
                <span className="text-xs font-bold" style={{ color: v === null ? "#9ca3af" : factorColor(v) }}>
                  {v === null ? "—" : v.toFixed(2)}
                </span>
              </div>
              <div className="h-2 w-full rounded-full bg-gray-100">
                {v !== null && (
                  <div
                    className="h-2 rounded-full"
                    style={{ width: `${v * 100}%`, background: factorColor(v) }}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
