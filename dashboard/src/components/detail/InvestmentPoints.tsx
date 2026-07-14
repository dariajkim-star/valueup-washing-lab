import type { Tag } from "../../lib/investmentTags";

// UX-DR4 투자 포인트 카드 — 자동 태깅 결과 표시(순수 로직은 lib/investmentTags.ts).
// 3.4 리뷰 Med 반영: 3상태 구분 — ① 계산 중(입력 쿼리 미완료) ② 데이터 부족(근거 지표
// 전부 null → 판단 불가) ③ 데이터는 있으나 태그 기준 미충족. 셋을 한 문구로 뭉개지 않는다.
export function InvestmentPoints({
  tags,
  loading,
  hasBasis,
}: {
  tags: Tag[];
  loading: boolean;
  hasBasis: boolean;
}) {
  const valueup = tags.filter((t) => t.group === "valueup");
  const mna = tags.filter((t) => t.group === "mna");

  if (loading) {
    return (
      <div className="rounded-xl border border-gray-100 bg-white p-5 text-sm text-gray-400">
        투자 포인트 계산 중…
      </div>
    );
  }

  if (tags.length === 0) {
    return (
      <div className="rounded-xl border border-gray-100 bg-white p-5 text-sm text-gray-400">
        {hasBasis
          ? "현재 자동 태깅 기준을 충족한 투자 포인트가 없습니다"
          : "데이터 부족으로 투자 포인트를 판단할 수 없습니다"}
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-100 bg-white p-5">
      <h3 className="mb-3 text-sm font-bold text-gray-900">투자 포인트 (자동 태깅)</h3>
      {valueup.length > 0 && (
        <>
          <span className="text-[10px] font-bold text-emerald-600">밸류업</span>
          <div className="mb-3 mt-1.5 flex flex-col gap-1.5">
            {valueup.map((t) => (
              <TagRow key={t.label} label={t.label} color="emerald" />
            ))}
          </div>
        </>
      )}
      {mna.length > 0 && (
        <>
          <span className="text-[10px] font-bold text-indigo-600">M&A</span>
          <div className="mt-1.5 flex flex-col gap-1.5">
            {mna.map((t) => (
              <TagRow key={t.label} label={t.label} color="indigo" />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function TagRow({ label, color }: { label: string; color: "emerald" | "indigo" }) {
  const bg = color === "emerald" ? "#f0fdf4" : "#eef2ff";
  const fg = color === "emerald" ? "#166534" : "#4338ca";
  return (
    <div className="flex items-center gap-2 rounded-lg px-3 py-2.5" style={{ background: bg }}>
      <span className="h-2 w-2 rounded-full" style={{ background: fg }} />
      <span className="text-xs font-semibold" style={{ color: fg }}>
        {label}
      </span>
    </div>
  );
}
