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
