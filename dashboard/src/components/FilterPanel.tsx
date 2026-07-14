import { useFilters } from "../state/filters";

// UX-DR1: 시장·업종·시총·지표 슬라이더·워싱 토글·스코어 모드 전환.
// 3.3 스코프에서는 시장·워싱 토글·스코어 모드를 실제 동작으로, 나머지(업종/시총/슬라이더)는
// 시안 재현 UI로 둔다(즉시 필터의 핵심 경로를 먼저 검증 — 슬라이더 배선은 후속 확장).

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="text-[11px] font-semibold text-gray-500">{title}</div>
      {children}
    </div>
  );
}

function Slider({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-700">{label}</span>
        <span className="text-[11px] text-gray-500">{value}</span>
      </div>
      <div className="h-1 rounded-full bg-gray-200">
        <div className="h-1 w-1/3 rounded-full bg-emerald-500" />
      </div>
    </div>
  );
}

export function FilterPanel() {
  const { scoreMode, setScoreMode, market, setMarket, washingOnly, setWashingOnly } = useFilters();

  return (
    <aside className="flex w-[300px] shrink-0 flex-col gap-5 bg-white p-5">
      <div>
        <div className="text-base font-bold leading-tight">밸류업 워싱</div>
        <div className="text-base font-bold leading-tight">스크리너</div>
        <div className="mt-0.5 text-[11px] text-gray-400">KOSPI · 애널리스트용</div>
      </div>

      {/* 스코어 모드 전환(UX-DR1 핵심) */}
      <Section title="스코어 모드">
        <div className="flex gap-0.5 rounded-lg bg-gray-100 p-0.5">
          {(["valueup", "mna"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setScoreMode(m)}
              className={`flex-1 rounded-md py-2 text-xs font-semibold transition ${
                scoreMode === m ? "bg-emerald-600 text-white" : "text-gray-500"
              }`}
            >
              {m === "valueup" ? "Value-up" : "M&A"}
            </button>
          ))}
        </div>
      </Section>

      {/* 시장(실동작) */}
      <Section title="시장">
        {(["KOSPI", "KOSDAQ"] as const).map((mk) => {
          const active = market === mk;
          return (
            <label key={mk} className="flex cursor-pointer items-center gap-2">
              <input
                type="radio"
                name="market"
                checked={active}
                onChange={() => setMarket(active ? undefined : mk)}
                className="accent-emerald-600"
              />
              <span className="text-[13px] text-gray-700">{mk}</span>
            </label>
          );
        })}
        <button onClick={() => setMarket(undefined)} className="self-start text-[11px] text-gray-400 underline">
          전체
        </button>
      </Section>

      <Slider label="ROE ≥" value="8%" />
      <Slider label="PBR ≤" value="1.5x" />
      <Slider label="EV/EBITDA ≤" value="12x" />
      <Slider label="부채비율 ≤" value="120%" />

      {/* 워싱 토글(실동작) */}
      <button
        onClick={() => setWashingOnly(!washingOnly)}
        className="flex items-center justify-between rounded-lg px-3 py-3 text-left"
        style={{ background: washingOnly ? "#fee4e2" : "#fef3f2" }}
      >
        <span className="text-xs font-semibold text-red-700">⚠ 워싱 의심만 보기</span>
        <span
          className="relative h-5 w-9 rounded-full transition"
          style={{ background: washingOnly ? "#b42318" : "#d1d5db" }}
        >
          <span
            className="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all"
            style={{ left: washingOnly ? 18 : 2 }}
          />
        </span>
      </button>
    </aside>
  );
}
