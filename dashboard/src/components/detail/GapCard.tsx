import { useRefreshCompany, type GapDetail } from "../../api/detail";
// WashingBadge: 파티 결정 B로 렌더 임시 은닉(로직·API 무변경). 은퇴/재정의는 opacity_rank 스토리에서.

// UX-DR3 "계획 vs 실제" 갭 카드(3.2 시안 재현). null 계약은 리스트와 동일 —
// washing_flag=판단불가 배지 재사용, 지표 null은 "—"(0 표시 금지).
export function GapCard({ gap }: { gap: GapDetail | null }) {
  if (!gap) {
    return (
      <div className="rounded-xl border border-gray-100 bg-white p-5 text-sm text-gray-400">
        밸류업 계획 데이터가 없습니다(엔진 미집계)
      </div>
    );
  }

  const fmt = (v: number | null, unit = "%") => (v === null ? "—" : `${v.toFixed(1)}${unit}`);
  // `v ? v*100 : null`은 정상값 0을 판단불가("—")로 세탁한다(3.4 리뷰 High — 백엔드가
  // 1.8부터 지킨 null≠0 계약의 프론트 위반). 명시적 null 비교만 허용.
  const percentage = (v: number | null) => (v === null ? null : v * 100);

  return (
    <div className="rounded-xl border border-gray-100 bg-white p-5">
      <h3 className="mb-4 text-sm font-bold text-gray-900">계획 vs 실제 (밸류업 이행)</h3>
      <div className="flex items-center gap-0">
        <Stat label="목표 ROE" value={fmt(gap.target_roe)} color="#6b7280" />
        <span className="px-2 text-lg text-gray-300">→</span>
        <Stat label="실제 ROE" value={fmt(gap.actual_roe)} color="#0e9f6e" />
        <Stat
          label="갭"
          value={gap.roe_gap === null ? "—" : `${gap.roe_gap >= 0 ? "+" : ""}${gap.roe_gap.toFixed(1)}%p`}
          // null은 중립 회색 — 빨간색(적자·실패 의미)으로 표시하면 판단불가가 부정 신호로 오독됨
          color={gap.roe_gap === null ? "#9ca3af" : gap.roe_gap >= 0 ? "#0e9f6e" : "#dc2626"}
        />
      </div>
      <div className="mt-4 flex gap-3">
        <MiniStat label="달성률" value={fmt(percentage(gap.achievement_rate))} />
        <MiniStat label="진척률" value={fmt(percentage(gap.progress_rate))} />
        <MiniStat label="자사주" value={buybackLabel(gap.buyback_status)} />
      </div>
      {/* [2026-07-23 파티 결정 B] washing_flag 화면 임시 은닉 — 로직·API 무변경. ScreenerTable 참조.
      <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
        워싱 판정: <WashingBadge flag={gap.washing_flag} />
      </div> */}

      <PlanProvenance gap={gap} />
    </div>
  );
}

// [2026-07-29] 출처 표기 + 새로고침.
// 왜 필요한가: 지금까지 화면은 "목표 ROE 10%"만 보여주고 **그 숫자가 언제 공시인지**를
// 말하지 않았다. 자유서식 공시는 회사가 여러 번 내고, 실측상 7종목은 최신 공시보다
// 과거 공시에 목표가 더 많다(엔진은 최신 1건만 채택). 공시일 없이 목표만 보이면
// 사용자가 그 값의 신선도를 판단할 수 없다.
function PlanProvenance({ gap }: { gap: GapDetail }) {
  const refresh = useRefreshCompany(gap.corp_code);
  const r = refresh.data;

  return (
    <div className="mt-4 border-t border-gray-100 pt-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-[10px] font-semibold text-gray-400">출처</span>
          {gap.plan_disclosure_date ? (
            <span className="text-[11px] text-gray-600">
              {gap.plan_disclosure_date} 공시 기준
              {gap.plan_rcept_no ? (
                // 접수번호가 있을 때만 링크 — 없는 링크를 만들어내지 않는다.
                <>
                  {" · "}
                  <a
                    href={`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${gap.plan_rcept_no}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 underline"
                    title={`DART 원문 보기 (접수번호 ${gap.plan_rcept_no})`}
                  >
                    DART 원문
                  </a>
                </>
              ) : (
                // null을 빈칸으로 뭉개지 않는다 — 왜 링크가 없는지 말한다.
                <span className="text-gray-400"> · 접수번호 미보유(재수집 필요)</span>
              )}
            </span>
          ) : (
            <span className="text-[11px] text-gray-400">계획 공시 없음</span>
          )}

          {/* 폴백 사실 자체가 출처의 일부다 — 공시일만 쓰면 "왜 최신이 아닌가"를
              사용자가 알 수 없고, 낡은 데이터로 오해하기 쉽다. 실제로는 최신 공시가
              목표 없는 표지 통지문이라 그 이전 공시를 근거로 삼은 것이다. */}
          {gap.plan_is_fallback && gap.plan_newest_disclosure_date && (
            <span className="mt-0.5 text-[10px] text-amber-700">
              ↑ 최신 공시({gap.plan_newest_disclosure_date})에는 목표가 없어 그 이전 공시를 사용
            </span>
          )}

          {/* [2026-07-29] 목표가 비어 있을 때 **왜**인지 말한다.
              "미공시"와 "다른 지표로 공시"는 다른 사실이다 — LG엔솔은 매출 2배·EBITDA
              Margin 10% 중반을 명확히 약속했다. 그걸 "순위 불가"로만 표시하면 부실 공시로
              읽히는데, 부실한 건 그 회사가 아니라 우리 자다. */}
          <BodySignalNote signal={gap.plan_body_signal} />
        </div>

        <button
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          className="shrink-0 rounded-lg border border-gray-200 px-2.5 py-1.5 text-[11px] font-semibold text-gray-700 disabled:opacity-50"
          title="DART에서 이 종목의 밸류업 공시를 다시 받아 점수를 재계산합니다. 불투명도 순위는 전 종목이 함께 재계산됩니다."
        >
          {refresh.isPending ? "갱신 중…" : "업데이트"}
        </button>
      </div>

      {/* 결과는 단계별로 말한다 — '완료' 한 단어로 뭉치면 목표가 여전히 비어 있을 때
          사용자가 무엇이 안 된 건지 알 수 없다. */}
      {refresh.isError && (
        <p className="mt-2 text-[11px] text-red-600">
          갱신 실패: {(refresh.error as Error).message}
        </p>
      )}
      {r && (
        <p className={`mt-2 text-[11px] ${r.complete ? "text-emerald-700" : "text-amber-700"}`}>
          {r.complete ? "갱신 완료" : "부분 갱신"} · 공시 {r.plans_ingested}건 수집
          {!r.ingest_ok && r.ingest_error ? ` · 수집 실패(${r.ingest_error})` : ""}
          {!r.scored ? ` · 채점 실패${r.score_error ? `(${r.score_error})` : ""}` : ""}
          {!r.opacity_reranked ? " · 불투명도 재계산 실패" : ""}
          {r.warnings.map((w) => ` · ${w}`).join("")}
        </p>
      )}
    </div>
  );
}

// 라벨은 목록 배지(BuybackRetiredBadge)와 같은 이유로 "이행"을 쓰지 않는다:
// buyback_status는 계획 기간과 무관한 **직전 재무 기간**의 소각 수량이라, 약속 이행을
// 뜻하지 않는다(실측: retired 16종목 중 계획 기간 내는 5). 두 화면이 다른 단어를 쓰면
// 같은 값이 다른 뜻으로 읽힌다.
function buybackLabel(status: string | null): string {
  switch (status) {
    case "retired":
      return "최근 소각";
    case "purchased_only":
      return "매입만·미소각";
    case "none":
      return "미실행";
    default:
      return "판단 불가";
  }
}

// 본문이 우리 4축을 못 채운 이유. axis_targets(정상)는 굳이 말하지 않는다 — 값이 이미
// 화면에 있으므로 설명이 노이즈다. 나머지 셋만 각자 다른 행동을 함의하므로 구분해 쓴다.
function BodySignalNote({ signal }: { signal: string | null }) {
  if (!signal || signal === "axis_targets") return null;
  const NOTE: Record<string, { text: string; tone: string }> = {
    // 부실 공시가 아니다 — 회사는 명확히 약속했고 우리 자에 그 눈금이 없다.
    other_metric: {
      text: "이 회사는 목표를 공시했으나 우리가 재는 4축(ROE·환원율·기간·자사주) 밖의 지표다(예: 매출·EBITDA·CapEx).",
      tone: "#1d4ed8",
    },
    // 계획 문서가 아니라 다른 공시를 가리키는 행정적 재공시.
    refiling: {
      text: "이 공시는 계획이 아니라 다른 공시를 가리키는 재공시다 — 위 출처가 그 실제 계획이다.",
      tone: "#b45309",
    },
    // 진짜 표지 통지문. 첨부·웹페이지에 실물이 있다.
    no_targets: {
      text: "본문에 목표 수치가 없다 — 실제 계획은 첨부나 회사 웹페이지에 있다(수집 범위 밖).",
      tone: "#6b7280",
    },
  };
  const note = NOTE[signal];
  if (!note) return null;
  return (
    <span className="mt-1 text-[10px] leading-snug" style={{ color: note.tone }}>
      {note.text}
    </span>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex flex-1 flex-col gap-1">
      <span className="text-[11px] font-semibold text-gray-500">{label}</span>
      <span className="text-2xl font-bold" style={{ color }}>
        {value}
      </span>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-1 flex-col gap-1 rounded-lg bg-gray-50 px-3.5 py-3">
      <span className="text-[10px] font-semibold text-gray-500">{label}</span>
      <span className="text-base font-bold text-gray-900">{value}</span>
    </div>
  );
}
