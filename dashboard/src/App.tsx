import { useFilters, toParams } from "./state/filters";
import { useScreening } from "./api/screening";
import { FilterPanel } from "./components/FilterPanel";
import { ScreenerTable } from "./components/ScreenerTable";

export default function App() {
  const filters = useFilters();
  const params = toParams(filters);
  // isPlaceholderData: keepPreviousData가 새 필터 응답 도착 전까지 이전 결과를 제공 —
  // 그대로 두면 "새 조건 라벨 아래 이전 결과"가 보인다(재리뷰 #4). 오버레이로 명시.
  const { data, isFetching, isPlaceholderData, error } = useScreening(params);

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
        <div className={isPlaceholderData ? "pointer-events-none opacity-50" : ""}>
          {isPlaceholderData && (
            <div className="mb-2 rounded-lg bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
              새 조건으로 다시 계산 중 — 아래는 이전 조건의 결과입니다
            </div>
          )}
          <ScreenerTable
            rows={data?.items ?? []}
            total={data?.total ?? 0}
            loading={isFetching}
            error={error}
          />
        </div>
      </main>
    </div>
  );
}
