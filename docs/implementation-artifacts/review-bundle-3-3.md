# Review Bundle — Story 3.3: 스크리너 필터·리스트 (React) (2026-07-13)

역할: 컨텍스트 없는 시니어 React/TS 리뷰어. 아래 AC·제약·코드(verbatim)만 보고 실제 버그·계약 위반·상태관리 결함을 찾아라. 스타일보다 동작 결함 우선.

## AC 요약
1. dashboard/ React19+Vite 스캐폴딩, 필터패널+종목리스트 렌더.
2. 필터 조작(시장·워싱·스코어모드 등) → 즉시 재쿼리.
3. TanStack Table, null 시각 언어 6상태(판단불가/산출불가/미집계/미지원업종/근거없음/워싱의심)+population_basis.
4. 서버상태=TanStack Query(/screening만, AD-11), UI상태=zustand 분리.
5. 정렬(field/-field)·페이지네이션 봉투 정합, 400/422/404 에러계약 화면 안깨짐.
6. 스코어 모드 전환 → 기본 정렬 스왑(execution_score↑ ↔ -mna_target_score).

## 제약
- AD-11: REST(/screening)만, DB 직접접근 없음. 서버/UI 상태 분리.
- 2.6 계약: 빈 문자열 필터는 422 → 프론트가 미선택을 빈 파라미터로 보내면 안 됨(client.ts가 제거).
- null 금칙: 빈칸·0·"아니오" 금지. has_*_score=false(미집계) ≠ score=null(산출불가) 구분.

## 알려진 것(재보고 불필요)
- 슬라이더·업종·시총 필터는 시안 UI만(배선 후속) — 의도적 스코프.
- 스크린샷 캡처는 환경 이슈로 타임아웃(기능은 read_page/클릭/JS로 검증됨).
- 미지원업종 판정은 프론트가 sector KSIC 64~66으로 근사(백엔드는 mna null만 줌).

## 코드 (verbatim)

### `dashboard/vite.config.ts`

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// AD-11: 프론트는 REST API로만 데이터 접근. dev proxy로 /api → FastAPI(127.0.0.1:8000)에
// 넘겨 CORS·하드코딩 URL을 피한다. 프로덕션은 리버스 프록시가 동일 경로를 담당.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5175,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});

```

### `dashboard/src/main.tsx`

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App.tsx";
import "./index.css";

// 서버 상태 전담(AD-11). UI 상태(필터·모드)는 zustand로 별도 관리.
const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);

```

### `dashboard/src/App.tsx`

```tsx
import { useFilters, toParams } from "./state/filters";
import { useScreening } from "./api/screening";
import { FilterPanel } from "./components/FilterPanel";
import { ScreenerTable } from "./components/ScreenerTable";

export default function App() {
  const filters = useFilters();
  const params = toParams(filters);
  const { data, isFetching, error } = useScreening(params);

  return (
    <div className="flex min-h-screen">
      <FilterPanel />
      <main className="flex-1 p-7">
        <header className="mb-4 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-gray-900">종목 리스트</h1>
            <p className="text-xs text-gray-500">
              {data ? `${data.total}개 종목` : "…"} ·{" "}
              {filters.scoreMode === "valueup" ? "Value-up" : "M&A"} 모드
            </p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-700">
            정렬: {filters.sort}
          </div>
        </header>
        <ScreenerTable
          rows={data?.items ?? []}
          total={data?.total ?? 0}
          loading={isFetching}
          error={error}
        />
      </main>
    </div>
  );
}

```

### `dashboard/src/api/client.ts`

```ts
// REST 접근 단일 지점(AD-11). /api 프리픽스는 Vite dev proxy가 FastAPI로 넘긴다.

export interface ApiError {
  detail: unknown;
  code?: string;
  status: number;
}

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly detail: unknown;
  constructor(e: ApiError) {
    super(typeof e.detail === "string" ? e.detail : `HTTP ${e.status}`);
    this.status = e.status;
    this.code = e.code;
    this.detail = e.detail;
  }
}

export async function apiGet<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const qs = new URLSearchParams();
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      // 미선택(undefined/null/"")은 아예 보내지 않는다 — 2.6이 빈 문자열 필터를 422로
      // 거부하므로, 프론트는 미선택을 빈 파라미터로 흘려보내지 않는다.
      if (v === undefined || v === null || v === "") continue;
      qs.append(k, String(v));
    }
  }
  const url = `/api${path}${qs.toString() ? `?${qs}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    let body: { detail?: unknown; code?: string } = {};
    try {
      body = await res.json();
    } catch {
      /* 본문 없는 에러 */
    }
    throw new ApiRequestError({ detail: body.detail ?? res.statusText, code: body.code, status: res.status });
  }
  return (await res.json()) as T;
}

```

### `dashboard/src/api/screening.ts`

```ts
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { apiGet } from "./client";

// 2.6 ScreeningOut 스키마와 1:1. null 계약이 타입에 그대로 드러난다.
export interface ScreeningRow {
  corp_code: string;
  corp_name: string | null;
  market: string | null;
  sector: string | null;
  as_of: string;
  execution_score: number | null;
  washing_flag: boolean | null; // true=워싱의심 / false=근거없음 / null=판단불가
  buyback_status: string | null;
  buyback_executed: boolean | null;
  mna_target_score: number | null; // null=산출불가(엄격 게이팅)
  population_basis: string | null; // sector:{KSIC} / market_fallback / market
  has_valueup_score: boolean; // false=엔진 미집계(산출불가와 구분)
  has_mna_score: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

export type ScoreMode = "valueup" | "mna";

export interface ScreeningParams {
  market?: string;
  sector?: string;
  min_execution_score?: number;
  max_execution_score?: number;
  min_mna_score?: number;
  max_mna_score?: number;
  washing_only?: boolean;
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

```

### `dashboard/src/state/filters.ts`

```ts
import { create } from "zustand";
import type { ScoreMode, ScreeningParams } from "../api/screening";

// UI 상태(필터·스코어 모드·정렬·페이지) — 서버 상태(TanStack Query)와 분리(AD-11).

const DEFAULT_SORT: Record<ScoreMode, string> = {
  valueup: "execution_score", // 이행 나쁜 순(오름차순) = 워싱 방향
  mna: "-mna_target_score", // 인수 매력 높은 순(내림차순)
};

interface FilterState {
  scoreMode: ScoreMode;
  market?: string; // "KOSPI" | "KOSDAQ" | undefined(전체)
  sector?: string; // KSIC prefix
  minExecutionScore?: number;
  maxExecutionScore?: number;
  minMnaScore?: number;
  maxMnaScore?: number;
  washingOnly: boolean;
  buybackExecuted?: boolean;
  sort: string;
  page: number;
  size: number;
  setScoreMode: (m: ScoreMode) => void;
  setMarket: (m?: string) => void;
  setWashingOnly: (v: boolean) => void;
  setSort: (s: string) => void;
  setPage: (p: number) => void;
  patch: (p: Partial<FilterState>) => void;
}

export const useFilters = create<FilterState>((set) => ({
  scoreMode: "valueup",
  washingOnly: false,
  sort: DEFAULT_SORT.valueup,
  page: 1,
  size: 20,
  // 스코어 모드 전환 시 기본 정렬을 그 모드의 관점으로 스왑 + 1페이지로(6번 AC)
  setScoreMode: (m) => set({ scoreMode: m, sort: DEFAULT_SORT[m], page: 1 }),
  setMarket: (market) => set({ market, page: 1 }),
  setWashingOnly: (washingOnly) => set({ washingOnly, page: 1 }),
  setSort: (sort) => set({ sort, page: 1 }),
  setPage: (page) => set({ page }),
  patch: (p) => set({ ...p, page: 1 }),
}));

// 스토어 상태 → API 파라미터(미선택은 client.ts가 걸러냄)
export function toParams(s: FilterState): ScreeningParams {
  return {
    market: s.market,
    sector: s.sector,
    min_execution_score: s.minExecutionScore,
    max_execution_score: s.maxExecutionScore,
    min_mna_score: s.minMnaScore,
    max_mna_score: s.maxMnaScore,
    washing_only: s.washingOnly || undefined,
    buyback_executed: s.buybackExecuted,
    sort: s.sort,
    page: s.page,
    size: s.size,
  };
}

export { DEFAULT_SORT };

```

### `dashboard/src/components/badges.tsx`

```tsx
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

// 은행·보험 등 M&A 스코어가 구조적으로 산출 불가한 업종(KSIC 64~66 금융·보험)
function isUnsupportedSector(sector: string | null): boolean {
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

```

### `dashboard/src/components/FilterPanel.tsx`

```tsx
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

```

### `dashboard/src/components/ScreenerTable.tsx`

```tsx
import { useMemo } from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import type { ScreeningRow } from "../api/screening";
import { useFilters } from "../state/filters";
import { MarketPill, MnaCell, ValueUpCell, WashingBadge } from "./badges";
import { ApiRequestError } from "../api/client";

const col = createColumnHelper<ScreeningRow>();

// 정렬 가능한 헤더 — 클릭 시 sort 토글(백엔드 field/-field 규약, AD-6)
function SortableHeader({ label, field, align }: { label: string; field?: string; align?: "right" }) {
  const { sort, setSort } = useFilters();
  if (!field) return <span>{label}</span>;
  const active = sort === field || sort === `-${field}`;
  const desc = sort === `-${field}`;
  return (
    <button
      onClick={() => setSort(desc ? field : `-${field}`)}
      className={`flex items-center gap-1 ${align === "right" ? "justify-end" : ""} ${
        active ? "text-gray-900" : "text-gray-500"
      }`}
    >
      {label}
      {active && <span>{desc ? "↓" : "↑"}</span>}
    </button>
  );
}

export function ScreenerTable({
  rows,
  total,
  loading,
  error,
}: {
  rows: ScreeningRow[];
  total: number;
  loading: boolean;
  error: unknown;
}) {
  const { scoreMode, page, size, setPage } = useFilters();

  const columns = useMemo(
    () => [
      col.accessor("corp_name", {
        header: () => <span>종목명</span>,
        cell: (c) => (
          <div className="flex flex-col">
            <span className="text-[13px] font-semibold text-gray-900">{c.getValue() ?? "—"}</span>
            <span className="text-[10px] text-gray-400">{c.row.original.corp_code}</span>
          </div>
        ),
      }),
      col.accessor("market", {
        header: () => <span>시장</span>,
        cell: (c) => <MarketPill market={c.getValue()} />,
      }),
      col.display({
        id: "valueup",
        header: () => <SortableHeader label="Value-up" field="execution_score" align="right" />,
        cell: (c) => (
          <div className="text-right">
            <ValueUpCell row={c.row.original} />
          </div>
        ),
      }),
      col.display({
        id: "mna",
        header: () => <SortableHeader label="M&A" field="mna_target_score" align="right" />,
        cell: (c) => (
          <div className="flex justify-end">
            <MnaCell row={c.row.original} />
          </div>
        ),
      }),
      col.accessor("washing_flag", {
        header: () => <span>워싱</span>,
        cell: (c) => <WashingBadge flag={c.getValue()} />,
      }),
    ],
    [],
  );

  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() });
  const totalPages = Math.max(1, Math.ceil(total / size));

  if (error) {
    const msg =
      error instanceof ApiRequestError
        ? `${error.code ?? error.status}: ${typeof error.detail === "string" ? error.detail : "요청 오류"}`
        : "데이터를 불러오지 못했습니다";
    return (
      <div className="rounded-xl border border-red-100 bg-red-50 p-6 text-sm text-red-700">{msg}</div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-100 bg-gray-50">
            {table.getHeaderGroups()[0].headers.map((h) => (
              <th
                key={h.id}
                className={`px-4 py-3 text-[11px] font-semibold text-gray-500 ${
                  h.id === "valueup" || h.id === "mna" ? "text-right" : "text-left"
                }`}
              >
                {flexRender(h.column.columnDef.header, h.getContext())}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && !loading && (
            <tr>
              <td colSpan={5} className="px-4 py-10 text-center text-sm text-gray-400">
                조건에 맞는 종목이 없습니다
              </td>
            </tr>
          )}
          {table.getRowModel().rows.map((r) => (
            <tr
              key={r.id}
              className="border-b border-gray-50"
              style={{ background: r.original.washing_flag === true ? "#fffbfa" : undefined }}
            >
              {r.getVisibleCells().map((cell) => (
                <td key={cell.id} className="px-4 py-3.5 align-middle">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      <div className="flex items-center justify-between border-t border-gray-100 px-4 py-3 text-xs text-gray-500">
        <span>
          총 {total}종목 · {scoreMode === "valueup" ? "Value-up" : "M&A"} 모드
          {loading && <span className="ml-2 text-gray-400">불러오는 중…</span>}
        </span>
        <div className="flex items-center gap-2">
          <button
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            className="rounded border border-gray-200 px-2 py-1 disabled:opacity-40"
          >
            이전
          </button>
          <span>
            {page} / {totalPages}
          </span>
          <button
            disabled={page >= totalPages}
            onClick={() => setPage(page + 1)}
            className="rounded border border-gray-200 px-2 py-1 disabled:opacity-40"
          >
            다음
          </button>
        </div>
      </div>
    </div>
  );
}

```
