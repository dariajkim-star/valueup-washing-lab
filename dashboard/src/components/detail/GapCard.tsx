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
      <PayoutAxis gap={gap} />
      <ExcludedAxes excluded={gap.excluded_axes} />
      {/* [2026-07-23 파티 결정 B] washing_flag 화면 임시 은닉 — 로직·API 무변경. ScreenerTable 참조.
      <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
        워싱 판정: <WashingBadge flag={gap.washing_flag} />
      </div> */}

      <PlanProvenance gap={gap} />
    </div>
  );
}

// [2026-07-31] 채점에서 **빠진** 축을 말한다.
//
// 계획 기간이 없으면 "진척 대비 달성"을 말할 수 없어 ROE 축을 채점에서 뺀다(AC3 유지).
// 예전엔 그 경우 점수가 통째로 null이었는데, 환원·자사주를 실제로 잴 수 있는 종목까지
// 죽였다(실측 75행). 이제는 나머지 축으로 채점하되 — **뺐다는 사실을 여기서 말한다.**
// score_basis에서 조용히 사라지면 "애초에 ROE를 약속하지 않은 기업"과 구분되지 않는다.
const EXCLUDED_LABEL: Record<string, string> = {
  "roe:no_period": "ROE는 채점에서 제외됨 — 계획 기간이 공시에 없어 진척 대비 달성을 판단할 수 없습니다(목표·실적은 위에 그대로 표시).",
};

function ExcludedAxes({ excluded }: { excluded: string | null }) {
  if (!excluded) return null;
  const notes = excluded.split(",").map((k) => EXCLUDED_LABEL[k] ?? k).filter(Boolean);
  if (!notes.length) return null;
  return (
    <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
      {notes.map((n) => (
        <p key={n} className="text-[11px] leading-relaxed text-amber-800">{n}</p>
      ))}
    </div>
  );
}

// [2026-07-31] 환원 축(배당성향·총주주환원율)의 목표 → 실적 → **달성 배율**.
//
// 왜 필요한가: 화면은 ROE 축만 목표/실적을 보여줬다. 그래서 `score_basis="payout"`인
// 100점이 왜 100점인지 확인할 방법이 없었다. 표본을 359로 늘려 실측하니 payout 단독
// 100점 21개사 중 **16개가 자기 과거 실적보다 낮은 목표**였다(목표 배당성향 10% / 실적
// 33.7%). 점수는 [0,1] clamp 때문에 과달성을 지우므로, 낮은 목표일수록 만점이 쉽다.
//
// 그래서 배율에 캡을 걸지 않고 원값을 쓴다. **판정하지 않는다** — "워싱"이라 부르지 않고
// "목표 대비 3.4배"라는 사실만 적는다. 왜 낮게 잡았는지는 우리가 알 수 없다(일회성 이익
// 기저효과일 수도 있다). 해석은 사용자 몫이고, 우리 몫은 격차를 감추지 않는 것이다.
function PayoutAxis({ gap }: { gap: GapDetail }) {
  // 채점과 같은 우선순위: 총주주환원율이 있으면 그쪽(더 포괄적인 약속)
  const useTotal = gap.target_total_return_ratio !== null;
  const target = useTotal ? gap.target_total_return_ratio : gap.target_payout_ratio;
  const actual = useTotal ? gap.actual_total_return_ratio : gap.actual_payout_ratio;
  if (target === null && actual === null) return null;
  const label = useTotal ? "총주주환원율" : "배당성향";
  const m = gap.payout_achievement;
  // 2배 이상만 강조 — 목표를 크게 웃돌면 "목표가 낮았다"는 신호가 강해진다.
  // 1배 미만(미달)은 빨강이 아니라 회색: 미달 자체는 점수에 이미 반영돼 있다.
  const tone = m === null ? "#9ca3af" : m >= 2 ? "#b45309" : "#6b7280";
  return (
    <div className="mt-3 flex items-center gap-3 rounded-lg bg-gray-50 px-3 py-2">
      <span className="text-[11px] font-semibold text-gray-600">{label}</span>
      <span className="text-xs text-gray-500">
        목표 {target === null ? "—" : `${target.toFixed(1)}%`}
        <span className="px-1.5 text-gray-300">→</span>
        실적 {actual === null ? "—" : `${actual.toFixed(1)}%`}
      </span>
      {m !== null && (
        <span
          className="ml-auto text-xs font-bold tabular-nums"
          style={{ color: tone }}
          title={
            m >= 2
              ? "실적이 목표를 크게 웃돈다 — 목표가 낮게 설정됐을 수 있다(판정 아님, 사실 표기)."
              : "실적 ÷ 목표. 1.0 초과는 목표 초과 달성."
          }
        >
          목표 대비 {m.toFixed(2)}배
        </span>
      )}
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
