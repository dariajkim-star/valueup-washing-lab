import type { Tag } from "../../lib/investmentTags";

// UX-DR4 투자 포인트 카드 — 자동 태깅 결과 표시(순수 로직은 lib/investmentTags.ts).
export function InvestmentPoints({ tags }: { tags: Tag[] }) {
  const valueup = tags.filter((t) => t.group === "valueup");
  const mna = tags.filter((t) => t.group === "mna");

  if (tags.length === 0) {
    return (
      <div className="rounded-xl border border-gray-100 bg-white p-5 text-sm text-gray-400">
        자동 태깅할 만한 셀링포인트가 없습니다(근거 지표 부족)
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
