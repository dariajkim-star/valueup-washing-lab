import type { ReturnBreakdownPoint } from "../../api/detail";

// [2026-08-04, Sally] 환원율 점프 설명 카드 — 점프의 "왜"를 문장이 아니라 **구성**으로
// 말한다. 총환원율이 갑자기 뛴 종목(실측: 에이피알 0%→55.7%, HD건설기계 10%→45.5% —
// 0026 단위 정정으로 자사주 취득액이 분자에 처음 합류하며 드러난 사실)의 연도별
// 배당 vs 자사주 취득 적층 막대. 증가분이 어느 색에서 왔는지가 곧 설명이다.
//
// null 계약(프로젝트 공통): 분자 구성이 미상(null)인 해는 막대를 그리지 않고 "산출 불가"로
// 남긴다 — 0으로 그리면 "환원 안 함"으로 세탁된다. 소각 0은 배지로 같은 자리에 남긴다
// (scoring.md 의도된 이중 시선: 환원율=매입 포함 업계 표준, 3단계 축=소각 기준).

const DIV_COLOR = "#94a3b8"; // 배당(중립 슬레이트 — 점수 색과 다른 축임을 색으로 구분)
const BB_COLOR = "#0e9f6e"; // 자사주 취득(emerald 계열 — 대시보드 강조색)

function fmtKrw(v: number | null): string {
  if (v === null) return "—"; // 미상 — 0으로 표시 금지
  if (v === 0) return "0";
  const eok = v / 100_000_000;
  return eok >= 10_000
    ? `${(eok / 10_000).toFixed(1)}조`
    : `${eok.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}억`;
}

export function ReturnBreakdownCard({ rows }: { rows: ReturnBreakdownPoint[] }) {
  // 연 단위 사실이므로 최근 5개 연도만 — 카드가 역사 전체를 떠안을 필요는 없다(차트가 있다)
  const recent = rows.slice(-5);
  if (recent.length === 0) {
    return (
      <div className="rounded-xl border border-gray-100 bg-white p-5">
        <h3 className="mb-2 text-sm font-bold text-gray-900">주주환원 구성</h3>
        <p className="py-4 text-center text-sm text-gray-400">연간 재무 데이터 없음</p>
      </div>
    );
  }

  // 막대 스케일: 산출 가능한 해의 최대 환원율(최소 100% — 낮은 값끼리도 비교 가능하게)
  const ratios = recent.map((r) => r.total_return_ratio).filter((v): v is number => v !== null);
  const scale = Math.max(100, ...ratios);

  const latest = recent[recent.length - 1];
  const prev = recent.length >= 2 ? recent[recent.length - 2] : undefined;
  const delta =
    latest.total_return_ratio !== null && prev !== undefined && prev.total_return_ratio !== null
      ? latest.total_return_ratio - prev.total_return_ratio
      : null;

  return (
    <div className="rounded-xl border border-gray-100 bg-white p-5">
      <div className="mb-1 flex items-baseline justify-between">
        <h3 className="text-sm font-bold text-gray-900">
          주주환원 구성{" "}
          <span className="text-[10px] font-normal text-gray-400">
            (배당 + 자사주 취득) / 순이익
          </span>
        </h3>
        {delta !== null && Math.abs(delta) >= 10 && (
          // 점프 배지: 전년 대비 ±10%p 이상일 때만 — 아래 막대가 그 이유를 말한다
          <span
            className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700"
            title="전년 대비 총주주환원율 변화 — 아래 구성 막대에서 배당·자사주 중 어느 쪽이 만든 변화인지 확인할 수 있다."
          >
            {delta > 0 ? "▲" : "▼"} {delta > 0 ? "+" : ""}
            {delta.toFixed(1)}%p YoY
          </span>
        )}
      </div>

      <div className="mt-3 flex flex-col gap-2">
        {recent.map((r) => {
          const ratio = r.total_return_ratio;
          const ni = r.net_income;
          // 막대 구성비: 배당·취득 각각의 순이익 대비 %(뷰와 같은 분모). 분자 구성이
          // null이면 막대를 그리지 않는다(산출 불가 — 0 세탁 금지).
          const divPct =
            ratio !== null && ni !== null && ni > 0 && r.dividend_total !== null
              ? (r.dividend_total * 100) / ni
              : null;
          const bbPct =
            ratio !== null && ni !== null && ni > 0 && r.buyback_amount_krw !== null
              ? (r.buyback_amount_krw * 100) / ni
              : null;
          return (
            <div key={r.year} className="grid grid-cols-[38px_1fr_52px] items-center gap-2.5">
              <span className="text-[11px] tabular-nums text-gray-400">{r.year}</span>
              <div className="flex h-4 overflow-hidden rounded bg-gray-100">
                {divPct !== null && bbPct !== null && (
                  <>
                    <div
                      style={{ width: `${(divPct / scale) * 100}%`, background: DIV_COLOR }}
                      title={`배당 ${fmtKrw(r.dividend_total)} (${divPct.toFixed(1)}%)`}
                    />
                    <div
                      style={{ width: `${(bbPct / scale) * 100}%`, background: BB_COLOR }}
                      title={`자사주 취득(CF) ${fmtKrw(r.buyback_amount_krw)} (${bbPct.toFixed(1)}%)`}
                    />
                  </>
                )}
              </div>
              <span className="text-right text-[11px] font-semibold tabular-nums text-gray-700">
                {ratio === null ? (
                  <span
                    className="font-normal text-gray-300"
                    title="분자 구성(배당 또는 자사주 취득)이 미상이라 산출 불가 — 0%가 아니다"
                  >
                    —
                  </span>
                ) : (
                  `${ratio.toFixed(1)}%`
                )}
              </span>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex items-center gap-4 text-[10px] text-gray-500">
        <span className="flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: DIV_COLOR }} />
          배당
        </span>
        <span className="flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: BB_COLOR }} />
          자사주 취득(CF)
        </span>
        {/* 소각 0 — 최신 연도의 사실 배지. 수량(주) 기준(>0)이며 금액 축과 별개다. */}
        {latest?.buyback_retired_qty === 0 &&
          latest.buyback_amount_krw !== null &&
          latest.buyback_amount_krw > 0 && (
            <span
              className="ml-auto rounded border border-amber-200 bg-amber-50 px-1.5 py-px text-[9px] font-semibold text-amber-700"
              title="최신 연도에 자사주 취득은 있었으나 소각 수량은 0 — 소각 전까지 자사주는 재매각(재발행)될 수 있다. 환원율(매입 포함)과 3단계 축(소각 기준)의 의도된 차이가 이 신호다."
            >
              매입만 · 소각 0
            </span>
          )}
      </div>
    </div>
  );
}
