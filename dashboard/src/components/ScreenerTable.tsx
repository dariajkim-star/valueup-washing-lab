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
      // 핵심지표(AC3, 3.3 리뷰 반영) — null=지표 없음("—", 0으로 표시 금지)
      col.accessor("roe", {
        header: () => <span className="block text-right">ROE</span>,
        cell: (c) => {
          const v = c.getValue();
          return (
            <div className="text-right text-xs text-gray-700">
              {v === null ? <span className="text-gray-300">—</span> : `${v.toFixed(1)}%`}
            </div>
          );
        },
      }),
      col.accessor("pbr", {
        header: () => <span className="block text-right">PBR</span>,
        cell: (c) => {
          const v = c.getValue();
          return (
            <div className="text-right text-xs text-gray-700">
              {v === null ? <span className="text-gray-300">—</span> : `${v.toFixed(2)}x`}
            </div>
          );
        },
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

  // AC6 강조 컬럼(재리뷰 #6): 활성 스코어 모드의 컬럼 전체를 배경 틴트로 강조
  const highlightedCol = scoreMode === "valueup" ? "valueup" : "mna";
  const highlightClass = (colId: string) =>
    colId === highlightedCol ? (scoreMode === "valueup" ? "bg-emerald-50/70" : "bg-indigo-50/70") : "";

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
                } ${highlightClass(h.id)}`}
              >
                {flexRender(h.column.columnDef.header, h.getContext())}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && !loading && (
            <tr>
              <td colSpan={7} className="px-4 py-10 text-center text-sm text-gray-400">
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
                <td key={cell.id} className={`px-4 py-3.5 align-middle ${highlightClass(cell.column.id)}`}>
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
