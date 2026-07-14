import { Link, useParams } from "react-router-dom";
import { useGapDetail, useMetricsByCorp, useMnaDetail } from "../api/detail";
import { useScreeningDetail } from "../api/screening";
import { GapCard } from "../components/detail/GapCard";
import { MetricsChart } from "../components/detail/MetricsChart";
import { MnaBreakdown } from "../components/detail/MnaBreakdown";
import { InvestmentPoints } from "../components/detail/InvestmentPoints";
import { MarketPill } from "../components/badges";
import { hasTagBasis, mnaTags, valueupTags } from "../lib/investmentTags";

// UX-DR3/UX-DR4 종목 상세 화면(3.2 Screen 2 시안).
//
// 시점 정합(3.4 리뷰 High): 화면 전체가 header(/screening)의 as_of 단일 기준일로 수렴 —
// gap·mna 쿼리는 header.as_of로 체이닝(두 API 모두 as_of 파라미터 기존재, 백엔드 무변경),
// 태그의 roe/pbr도 /metrics 시계열이 아니라 header 행에서 가져온다. 시계열 차트만 예외
// (본질이 "역사"라 시점 정합 위반이 아님).
//
// 에러 세탁 방지(3.4 리뷰 High): 각 쿼리의 isError를 구분 소비 — "미집계"는 성공 응답의
// 빈 결과일 때만, 요청 실패는 명시적 오류 카드로(장애를 정상 결측으로 위장 금지).
export default function CompanyDetail() {
  const { corpCode } = useParams<{ corpCode: string }>();

  const header = useScreeningDetail(corpCode);
  const asOf = header.data?.as_of;
  const gap = useGapDetail(corpCode, asOf);
  const mna = useMnaDetail(corpCode, asOf);
  const metrics = useMetricsByCorp(corpCode);

  const tags = [...valueupTags(header.data ?? null, gap.data ?? null), ...mnaTags(mna.data ?? null)];
  const tagInputsLoading = header.isLoading || gap.isLoading || mna.isLoading;
  const basis = hasTagBasis(header.data ?? null, gap.data ?? null, mna.data ?? null);

  return (
    <div className="min-h-screen bg-[#f5f6f8] p-7">
      <Link to="/" className="mb-4 inline-block text-xs font-semibold text-emerald-600">
        ← 리스트로
      </Link>

      {header.isError && (
        <div className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-xs font-semibold text-red-700">
          종목 정보를 불러오지 못했습니다 — 요청 오류(데이터 없음이 아닙니다)
        </div>
      )}

      <header className="mb-5 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold text-gray-900">{header.data?.corp_name ?? corpCode}</h1>
            <MarketPill market={header.data?.market ?? null} />
            <span className="text-xs text-gray-400">
              {corpCode} · {header.data?.sector ?? "—"}
            </span>
          </div>
          <p className="mt-1 text-[11px] text-gray-400">{asOf ? `기준일 ${asOf}` : "…"}</p>
        </div>
        <div className="flex gap-3">
          <ScoreChip label="실행점수" value={header.data?.execution_score ?? null} color="#0e9f6e" />
          <ScoreChip label="M&A 타겟" value={header.data?.mna_target_score ?? null} color="#65a30d" />
        </div>
      </header>

      <div className="flex gap-5">
        <div className="flex flex-1 flex-col gap-5">
          <div className="rounded-xl border border-gray-100 bg-white p-5">
            <h3 className="mb-3 text-sm font-bold text-gray-900">지표 분기 시계열 · ROE</h3>
            {metrics.isError ? (
              <ErrorNote what="지표 시계열" />
            ) : metrics.isLoading ? (
              <p className="py-8 text-center text-sm text-gray-400">불러오는 중…</p>
            ) : (
              <MetricsChart metrics={metrics.data ?? []} />
            )}
          </div>
          {gap.isError ? (
            <ErrorCard what="밸류업 갭 분석" />
          ) : gap.isLoading || !asOf ? (
            <LoadingCard />
          ) : (
            <GapCard gap={gap.data ?? null} />
          )}
        </div>
        <div className="flex w-[420px] shrink-0 flex-col gap-5">
          {mna.isError ? (
            <ErrorCard what="M&A 4요소 분해" />
          ) : mna.isLoading || !asOf ? (
            <LoadingCard />
          ) : (
            <MnaBreakdown mna={mna.data ?? null} />
          )}
          <InvestmentPoints tags={tags} loading={tagInputsLoading} hasBasis={basis} />
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

// 요청 실패는 "미집계/데이터 없음"과 명확히 구분되는 오류 표시(3.4 리뷰 High)
function ErrorCard({ what }: { what: string }) {
  return (
    <div className="rounded-xl border border-red-100 bg-red-50 p-5 text-sm text-red-700">
      {what}을(를) 불러오지 못했습니다 — 요청 오류(데이터 없음이 아닙니다)
    </div>
  );
}

function ErrorNote({ what }: { what: string }) {
  return (
    <p className="py-8 text-center text-sm text-red-600">
      {what}을(를) 불러오지 못했습니다 — 요청 오류
    </p>
  );
}
