import { useEffect, useRef, useState } from "react";
import { useFilters, DEFAULT_OPAQUE_MIN_RANK, type McapBucket } from "../state/filters";

// UX-DR1: 시장·업종·시총구간·지표 슬라이더·워싱 토글·스코어 모드 전환 — 전부 실배선
// (3.3 리뷰 반영: 가짜 컨트롤 금지, 모든 조작이 /screening 재요청으로 이어진다).

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="text-[11px] font-semibold text-gray-500">{title}</div>
      {children}
    </div>
  );
}

// KSIC 2자리 prefix 옵션(sector = DART induty_code 원문, 2.7 버킷 택소노미와 동일 단위)
const SECTOR_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "", label: "전체" },
  { value: "20", label: "화학 (20)" },
  { value: "21", label: "제약 (21)" },
  { value: "24", label: "금속 (24)" },
  { value: "26", label: "전자·반도체 (26)" },
  { value: "30", label: "자동차 (30)" },
  { value: "35", label: "전기·가스 (35)" },
  { value: "58", label: "출판·게임 (58)" },
  { value: "63", label: "정보서비스 (63)" },
  { value: "64", label: "금융 (64)" },
  { value: "65", label: "보험 (65)" },
];

const MCAP_OPTIONS: Array<{ value: McapBucket; label: string }> = [
  { value: "all", label: "전체" },
  { value: "large", label: "대형 (10조 이상)" },
  { value: "mid", label: "중형 (1조 이상 10조 미만)" },
  { value: "small", label: "소형 (1조 미만)" },
];

// 실동작 슬라이더: 드래그 중엔 로컬 값만, 놓는 순간(commit) 스토어 반영 → 재요청.
// (onChange마다 커밋하면 드래그 한 번에 요청 수십 발 — 커밋 시점 분리)
//
// 재리뷰(3차) 반영 — 이전 버전(local===undefined 가드)의 결함 3건을 `interacted` ref로
// 한 번에 해소:
//   1. 가드가 완전한 no-op이 아니었음 — onCommit(undefined)는 여전히 호출돼 부모의
//      patch()가 page를 1로 리셋(사용자가 아무것도 안 건드렸는데 페이지 이동).
//   2. 미설정 상태에서 슬라이더가 이미 min 위치라 그 값을 "명시 선택"할 방법이 없었음
//      (onChange 미발생 → 커밋 시 값 판별 불가).
//   3. pointerup 이후 blur가 이어지면 동일 값으로 커밋이 중복 호출됨.
// interacted=false(사용자가 change로 값을 만진 적 없음)면 모든 종료 이벤트에서 커밋을
// 완전히 스킵(호출 자체 없음), interacted=true면 커밋 후 즉시 false로 되돌려 중복 방지.
export function RangeFilter({
  label,
  unit,
  min,
  max,
  step,
  value,
  onCommit,
}: {
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  value?: number;
  onCommit: (v?: number) => void;
}) {
  const [local, setLocal] = useState<number | undefined>(value);
  const interacted = useRef(false);
  useEffect(() => setLocal(value), [value]); // 외부(스토어) 값 변경 동기화
  const active = local !== undefined;

  const commit = (v: number) => {
    if (!interacted.current) return; // 사용자가 change로 값을 만진 적 없음 → 완전 no-op
    interacted.current = false; // 커밋 즉시 리셋 — 후속 종료 이벤트의 중복 커밋 방지
    onCommit(v);
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-700">{label}</span>
        <span className="flex items-center gap-1.5 text-[11px] text-gray-500">
          {active ? `${local}${unit}` : "전체"}
          {active && (
            <button
              onClick={() => {
                interacted.current = false;
                setLocal(undefined);
                onCommit(undefined);
              }}
              className="text-gray-400 underline"
            >
              해제
            </button>
          )}
        </span>
      </div>
      <input
        type="range"
        aria-label={label}
        min={min}
        max={max}
        step={step}
        value={local ?? min}
        onChange={(e) => {
          interacted.current = true;
          setLocal(e.currentTarget.valueAsNumber);
        }}
        onPointerUp={(e) => commit(e.currentTarget.valueAsNumber)}
        onPointerCancel={(e) => commit(e.currentTarget.valueAsNumber)}
        onKeyUp={(e) => commit(e.currentTarget.valueAsNumber)}
        onBlur={(e) => commit(e.currentTarget.valueAsNumber)}
        className="h-1 w-full accent-emerald-600"
      />
    </div>
  );
}

export function FilterPanel() {
  const f = useFilters();
  const opaqueOn = f.opaqueMinRank !== undefined;
  const lowAmbitionOn = f.lowAmbitionMaxGap !== undefined;

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
              onClick={() => f.setScoreMode(m)}
              className={`flex-1 rounded-md py-2 text-xs font-semibold transition ${
                f.scoreMode === m ? "bg-emerald-600 text-white" : "text-gray-500"
              }`}
            >
              {m === "valueup" ? "Value-up" : "M&A"}
            </button>
          ))}
        </div>
      </Section>

      <Section title="시장">
        {(["KOSPI", "KOSDAQ"] as const).map((mk) => {
          const active = f.market === mk;
          return (
            <label key={mk} className="flex cursor-pointer items-center gap-2">
              <input
                type="radio"
                name="market"
                checked={active}
                onChange={() => f.setMarket(active ? undefined : mk)}
                className="accent-emerald-600"
              />
              <span className="text-[13px] text-gray-700">{mk}</span>
            </label>
          );
        })}
        <button onClick={() => f.setMarket(undefined)} className="self-start text-[11px] text-gray-400 underline">
          전체
        </button>
      </Section>

      <Section title="업종">
        <select
          value={f.sector ?? ""}
          onChange={(e) => f.setSector(e.target.value || undefined)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-[13px] text-gray-700"
        >
          {SECTOR_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </Section>

      <Section title="시총 구간">
        <select
          value={f.mcapBucket}
          onChange={(e) => f.setMcapBucket(e.target.value as McapBucket)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-[13px] text-gray-700"
        >
          {MCAP_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </Section>

      <RangeFilter label="ROE ≥" unit="%" min={0} max={30} step={1} value={f.minRoe} onCommit={(v) => f.patch({ minRoe: v })} />
      <RangeFilter label="PBR ≤" unit="x" min={0} max={5} step={0.1} value={f.maxPbr} onCommit={(v) => f.patch({ maxPbr: v })} />
      <RangeFilter label="EV/EBIT ≤" unit="x" min={0} max={50} step={1} value={f.maxEvEbit} onCommit={(v) => f.patch({ maxEvEbit: v })} />
      <RangeFilter label="부채비율 ≤" unit="%" min={0} max={300} step={10} value={f.maxDebtRatio} onCommit={(v) => f.patch({ maxDebtRatio: v })} />

      {/* 불투명 상위 필터(실동작) — 구 "워싱 의심만 보기" 대체.
          그 토글은 washing_flag(실측 True=0)에 걸려 **항상 빈 결과**를 냈다. 이제 고의
          판정이 아니라 공시 격차로 거른다.
          [2026-07-28] 임계 소유권 = 화면. 토글은 켜고 끄기만 하고(기본 위치로 켬),
          경계는 아래 다이얼로 사용자가 옮긴다 — 고정 임계를 숨긴 채 굳히지 않는다. */}
      <div
        className="flex flex-col gap-2 rounded-lg px-3 py-3"
        style={{ background: opaqueOn ? "#fef3c7" : "#fffbeb" }}
      >
        <button
          onClick={() => f.setOpaqueMinRank(opaqueOn ? undefined : DEFAULT_OPAQUE_MIN_RANK)}
          className="flex items-center justify-between text-left"
          aria-pressed={opaqueOn}
          title="공시하지 않은 목표 축이 peer 대비 많은 종목만 — 고의 판정이 아니라 공시 격차"
        >
          <span className="flex flex-col">
            <span className="text-xs font-semibold text-amber-800">◐ 불투명 상위만 보기</span>
            <span className="text-[10px] text-amber-700/70">
              {opaqueOn ? "peer 대비 미공시 축이 많은 상위 구간" : "꺼짐 — 전체 표시"}
            </span>
          </span>
          <span
            className="relative h-5 w-9 shrink-0 rounded-full transition"
            style={{ background: opaqueOn ? "#b45309" : "#d1d5db" }}
          >
            <span
              className="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all"
              style={{ left: opaqueOn ? 18 : 2 }}
            />
          </span>
        </button>

        {/* 다이얼은 켜져 있을 때만 — 꺼진 상태의 슬라이더는 "0으로 내리면 뭐가 되나"라는
            무의미한 질문을 만든다(rank≥0 = 전체 = 꺼짐과 동의어). */}
        {opaqueOn && (
          <RangeFilter
            label="경계(백분위) ≥"
            unit=""
            min={5}
            max={95}
            step={5}
            value={Math.round(f.opaqueMinRank! * 100)}
            onCommit={(v) => f.setOpaqueMinRank(v === undefined ? undefined : v / 100)}
          />
        )}

        {/* [P1-7 2026-08-03] 목표 야심도 필터. 실측: 만점 70건 중 40건이 자기 과거보다
            낮은 목표였는데 목록에서 구분되지 않았다 — 점수만 보면 셋 다 100점이다.
            불투명 다이얼과 같은 계열: 고의를 판정하지 않고 격차로 거른다. */}
        <button
          onClick={() => f.setLowAmbitionMaxGap(lowAmbitionOn ? undefined : 0)}
          className="mt-1 flex items-center justify-between border-t border-amber-200/60 pt-2 text-left"
          aria-pressed={lowAmbitionOn}
          title="공시한 목표가 자기 과거 실적보다 낮거나 같은 종목만 — 달성 여부(점수)와는 별개의 사실이다. 비교할 과거 실적이 없는 종목은 산출 불가라 매칭되지 않는다."
        >
          <span className="flex flex-col">
            <span className="text-xs font-semibold text-amber-800">↓ 과거 수준 이하 목표만</span>
            <span className="text-[10px] text-amber-700/70">
              {lowAmbitionOn ? "하던 것보다 낮거나 같게 약속한 종목" : "꺼짐 — 전체 표시"}
            </span>
          </span>
          <span
            className="relative h-5 w-9 shrink-0 rounded-full transition"
            style={{ background: lowAmbitionOn ? "#b45309" : "#d1d5db" }}
          >
            <span
              className="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all"
              style={{ left: lowAmbitionOn ? 18 : 2 }}
            />
          </span>
        </button>
      </div>
    </aside>
  );
}
