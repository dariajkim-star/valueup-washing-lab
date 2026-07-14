import { Link, useParams } from "react-router-dom";
import { useGapDetail, useMetricsByCorp, useMnaDetail } from "../api/detail";
import { useScreeningDetail } from "../api/screening";
import { GapCard } from "../components/detail/GapCard";
import { MetricsChart } from "../components/detail/MetricsChart";
import { MnaBreakdown } from "../components/detail/MnaBreakdown";
import { InvestmentPoints } from "../components/detail/InvestmentPoints";
import { MarketPill } from "../components/badges";
import { mnaTags, valueupTags } from "../lib/investmentTags";

// UX-DR3/UX-DR4 종목 상세 화면(3.2 Screen 2 시안). 4개 API 병렬 호출(AD-11 REST만):
// /screening(헤더) · /valueup/gap-analysis(갭카드) · /mna/ranking(4요소) · /metrics/{corp}(시계열).
export default function CompanyDetail() {
  const { corpCode } = useParams<{ corpCode: string }>();

  const { data: header } = useScreeningDetail(corpCode);
  const { data: gap, isLoading: gapLoading } = useGapDetail(corpCode);
  const { data: mna, isLoading: mnaLoading } = useMnaDetail(corpCode);
  const { data: metrics, isLoading: metricsLoading } = useMetricsByCorp(corpCode);

  const latestMetric = metrics?.[metrics.length - 1];
  const tags = [...valueupTags(latestMetric, gap ?? null), ...mnaTags(mna ?? null)];

  return (
    <div className="min-h-screen bg-[#f5f6f8] p-7">
      <Link to="/" className="mb-4 inline-block text-xs font-semibold text-emerald-600">
        ← 리스트로
      </Link>

      <header className="mb-5 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold text-gray-900">{header?.corp_name ?? corpCode}</h1>
            <MarketPill market={header?.market ?? null} />
            <span className="text-xs text-gray-400">
              {corpCode} · {header?.sector ?? "—"}
            </span>
          </div>
          <p className="mt-1 text-[11px] text-gray-400">
            {header?.as_of ? `as_of ${header.as_of}` : "…"}
          </p>
        </div>
        <div className="flex gap-3">
          <ScoreChip
            label="실행점수"
            value={header?.execution_score ?? null}
            color="#0e9f6e"
          />
          <ScoreChip
            label="M&A 타겟"
            value={header?.mna_target_score ?? null}
            color="#65a30d"
          />
        </div>
      </header>

      <div className="flex gap-5">
        <div className="flex flex-1 flex-col gap-5">
          <div className="rounded-xl border border-gray-100 bg-white p-5">
            <h3 className="mb-3 text-sm font-bold text-gray-900">지표 분기 시계열 · ROE</h3>
            {metricsLoading ? (
              <p className="py-8 text-center text-sm text-gray-400">불러오는 중…</p>
            ) : (
              <MetricsChart metrics={metrics ?? []} />
            )}
          </div>
          {gapLoading ? <LoadingCard /> : <GapCard gap={gap ?? null} />}
        </div>
        <div className="flex w-[420px] shrink-0 flex-col gap-5">
          {mnaLoading ? <LoadingCard /> : <MnaBreakdown mna={mna ?? null} />}
          <InvestmentPoints tags={tags} />
        </div>
      </div>
    </div>
  );
}

function ScoreChip({ label, value, color }: { label: string; value: number | null; color: string }) {
  return (
    <div className="rounded-xl border border-gray-100 bg-white px-4 py-3">
      <div className="text-[10px] font-semibold text-gray-500">{label}</div>
      <div className="flex items-center gap-1">
        <span className="text-xl font-bold" style={{ color: value === null ? "#9ca3af" : color }}>
          {value === null ? "—" : value.toFixed(0)}
        </span>
        <span className="text-[10px] text-gray-400">/100</span>
      </div>
    </div>
  );
}

function LoadingCard() {
  return (
    <div className="rounded-xl border border-gray-100 bg-white p-5 text-sm text-gray-400">
      불러오는 중…
    </div>
  );
}
