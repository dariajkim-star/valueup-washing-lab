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

// 5-1: execution_score는 **기업이 공시한 약속에 대해서만** 채점되므로 가중치 기반이 종목마다
// 다르다. 그 사실을 감추면 기준이 다른 점수를 같은 척도로 비교하게 된다 — null을 빈칸으로
// 뭉개지 않는다는 3.2 원칙과 같은 이유로, 근거를 점수 옆에 항상 붙인다.
const BASIS_LABEL: Record<string, string> = {
  roe: "ROE",
  buyback: "자사주",
  payout: "배당성향",
  total_return: "주주환원",
};

export function scoreBasisParts(basis: string): string[] {
  return basis.split("+").map((p) => BASIS_LABEL[p] ?? p);
}

export function ScoreBasisChip({ basis }: { basis: string | null }) {
  if (!basis) return null;
  const parts = scoreBasisParts(basis);
  const single = parts.length === 1;
  // 단일 항목은 특히 조심해야 한다 — 자사주 단독은 이진값이라 점수가 0 또는 100뿐이고,
  // 3개 항목으로 매긴 100점과 나란히 놓이면 같은 성취처럼 읽힌다.
  return (
    <span
      className="text-[9px]"
      style={{ color: single ? "#b45309" : "#9ca3af" }}
      title={
        single
          ? `${parts[0]} 항목 하나만 공시돼 그것만으로 채점됨 — 다항목 점수와 직접 비교 금지`
          : `공시한 ${parts.length}개 항목으로 채점: ${parts.join(", ")}`
      }
    >
      {single ? `${parts[0]}만` : parts.join("·")}
    </span>
  );
}

export function ValueUpCell({ row }: { row: ScreeningRow }) {
  if (!row.has_valueup_score) return <Pill text="미집계" fg="#9ca3af" dashed />;
  if (row.execution_score === null) {
    // 점수 null의 두 원인(약속 자체가 없음 / 약속은 있으나 실적 미상)은 API에서 구분되지
    // 않는다 — 둘 다 "판단 불가"로 정직하게 표시한다(추정해서 나누지 않는다).
    return (
      <div className="flex flex-col items-end gap-0.5">
        <span className="text-[15px] font-bold text-gray-400">—</span>
        <span className="text-[10px] text-gray-400">판단 불가</span>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-end gap-0.5">
      <span className="text-[15px] font-bold" style={{ color: scoreColor(row.execution_score) }}>
        {row.execution_score.toFixed(0)}
      </span>
      <ScoreBasisChip basis={row.score_basis} />
    </div>
  );
}

// 은행·보험 등 M&A 스코어가 구조적으로 산출 불가한 업종(KSIC 64~66 금융·보험).
// 리스트(MnaCell)와 상세(MnaBreakdown)가 같은 판정을 공유(3.4 리뷰 Med — 표현 불일치 방지).
export function isUnsupportedSector(sector: string | null): boolean {
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

// 불투명도 셀(washing_flag 대체) — 미공시 목표 축 수의 peer 백분위.
// 워싱 배지와 결정적으로 다른 점: **고의를 판정하지 않는다.** "이 기업이 속였다"가 아니라
// "이 공시로는 밸류를 판단할 근거가 부족하다"를 순위로 보여준다(레아 원칙).
export function OpacityCell({ row }: { row: ScreeningRow }) {
  if (!row.has_opacity_score || row.opacity_rank === null) {
    // 순위 불가 — 계획 미공시이거나 본문 4축이 전부 비어 **읽을 수 없는** 공시.
    // 0("최투명")으로도, 1("최불투명")으로도 표시하지 않는다. 못 읽은 걸 벌하지 않는다.
    // other_metric은 별도 표기(파티 결정 2026-07-29) — 회사는 명확히 약속했고(예: CapEx·
    // 매출·EBITDA) 우리 자에 그 눈금이 없을 뿐이다. "부실 공시"와 묶으면 판정이 된다.
    const otherMetric = row.plan_body_signal === "other_metric";
    return (
      <div className="flex flex-col items-end gap-0.5">
        <span className="text-[15px] font-bold text-gray-400">—</span>
        <span
          className="text-[10px] text-gray-400"
          title={otherMetric
            ? "목표를 공시했으나 우리가 재는 4축(ROE·환원율·기간·자사주) 밖의 지표다(예: 매출·EBITDA·CapEx). 상세 화면에 설명이 있다."
            : undefined}
        >
          {otherMetric ? "타 지표로 공시" : "순위 불가"}
        </span>
      </div>
    );
  }
  const pct = Math.round(row.opacity_rank * 100);
  // 불투명할수록 진해지는 단색 스케일(점수 색상과 다른 축임을 색으로도 구분).
  const fg = pct >= 70 ? "#b45309" : pct >= 40 ? "#a16207" : "#9ca3af";
  const n = row.opacity_count;
  return (
    <div className="flex flex-col items-end gap-0.5">
      <span
        className="text-[15px] font-bold"
        style={{ color: fg }}
        title={`peer 대비 공시 불투명도 상위 ${100 - pct}% (백분위 ${pct})`}
      >
        {pct}
      </span>
      <span className="text-[9px] text-gray-400">
        {n === null ? "—" : `미공시 ${n}축`}
      </span>
    </div>
  );
}

// [AC3] 자사주 소각 **사실** 배지.
// 은퇴한 워싱 배지의 대칭점이다: 워싱 배지는 고의를 판정해서(그리고 실측 True=0이라
// 켜지지도 않아서) 죽었지만, 소각은 DART에서 수량으로 확인되는 사실이다 — 판정이 아니라
// 관측. 그래서 "의심"이 아니라 사실만 말한다.
//
// retired일 때만 렌더한다:
//   - purchased_only(매입만)·none은 "안 했다"를 배지로 강조하는 꼴이라 판정에 가까워진다.
//   - unknown은 null — 못 읽은 걸 벌하지 않는다(OpacityCell '순위 불가'와 같은 원칙).
// 셋 다 상세의 GapCard에서 4상태 전부 정직하게 표시되므로 목록에서 생략해도 정보가
// 사라지지 않는다(목록은 사실 하나만, 상세는 전부).
//
// ⚠ [2026-07-28 실측 — 라벨을 "소각 이행"에서 "최근 소각"으로 바꾼 이유]
// buyback_status는 **밸류업 계획 기간과 무관하다.** gap_engine이 쓰는 값은
// `latest_financial_buyback`(valueup_score.py:74) — as_of 이전 **최신 재무 한 행**의
// 소각 수량이고, 계획 period_start~period_end로 걸러지지 않는다.
// retired 16종목을 계획 기간과 대조한 결과:
//     계획기간 안 5 · 계획 시작 전 3 · 계획 종료 후 1 · 계획기간 미상 7
// 즉 **열여섯 중 다섯**만 "약속한 기간에 소각했다"에 해당한다. 기아(이 프로젝트가
// 두 달간 모범으로 삼은 종목)조차 소각은 2024Q4인데 계획은 2025~2027 — 약속하기
// 전 해의 소각이다. 현대자동차는 계획이 2017~2022로 이미 끝났다.
// "이행"은 약속을 전제하는 단어라, 그 연결이 데이터에 없는데도 인과를 주장하고
// 있었다 — 우리가 washing_flag를 은퇴시킨 것과 같은 죄(없는 것을 있다고 말하기).
//
// 그렇다고 계획 기간으로 게이팅하지는 않는다: 미상 7종목을 "안 했다"로 미는 셈이라
// is_unrankable에서 지킨 원칙("못 읽은 걸 벌하지 않는다")을 정면으로 어긴다.
// 사실은 남기고, **사실에 붙인 문장만 정정한다.**
// ✅ [2026-07-31 P1-4] 이제 **시점을 판정한다** — 위 주석의 "연결이 데이터에 없다"가 해소됐다.
// 계획 기간을 아는 건은 기간으로, 모르는 건은 **공시일**로 잰다(disclosure_date는 전건 보유).
// 실측(retired 53건): 기간 내 5 · 기간 밖 11 · 공시 이전 30 · 같은 해 7(판정 불가).
// **약속 후 이행이 확인되는 것은 5건뿐**이고, 30건은 약속하기 전에 한 소각이다.
// 그래서 배지도 하나가 아니라 시점별로 다른 문장을 쓴다 — 초록(이행)을 아무에게나 주지 않는다.
const TIMING_BADGE: Record<string, { label: string; bg: string; fg: string; title: string }> = {
  in_period: {
    label: "계획 기간 내 소각", bg: "#dcfce7", fg: "#15803d",
    title: "밸류업 계획 기간 안에서 자사주를 소각했다 — 약속과 시점이 연결되는 유일한 경우다.",
  },
  outside_period: {
    label: "계획 기간 밖 소각", bg: "#fef3c7", fg: "#92400e",
    title: "소각은 있었으나 밸류업 계획 기간 밖이다(시작 전이거나 종료 후). 이행으로 볼 수 없다.",
  },
  after_disclosure: {
    label: "공시 후 소각", bg: "#dcfce7", fg: "#15803d",
    title: "계획 기간이 공시에 없어 공시일을 기준으로 판정했다 — 공시 연도보다 뒤 회계연도의 소각이다.",
  },
  before_disclosure: {
    label: "공시 전 소각", bg: "#fef3c7", fg: "#92400e",
    title: "계획을 공시하기 **전** 회계연도의 소각이다. 최근 소각이지만 이 약속의 이행은 아니다.",
  },
  same_year_unknown: {
    label: "소각(시점 미상)", bg: "#f3f4f6", fg: "#6b7280",
    title: "공시와 같은 해의 소각이라 재무 연 단위로는 전후를 가릴 수 없다 — 판정하지 않는다.",
  },
};

export function BuybackRetiredBadge(
  { status, timing }: { status: string | null; timing?: string | null },
) {
  if (status !== "retired") return null;
  const t = timing ? TIMING_BADGE[timing] : undefined;
  if (t) {
    return (
      <span
        className="inline-flex w-fit items-center rounded px-1.5 py-px text-[9px] font-semibold"
        style={{ background: t.bg, color: t.fg }}
        title={t.title}
      >
        {t.label}
      </span>
    );
  }
  // timing이 아직 없는 데이터(0022 이전 채점분) — 종전 라벨로 정직하게 남는다.
  return (
    <span
      className="inline-flex w-fit items-center rounded px-1.5 py-px text-[9px] font-semibold"
      style={{ background: "#dcfce7", color: "#15803d" }}
      title="직전 재무 기간에 자사주 소각 수량 > 0 (DART 취득/처분현황). 밸류업 계획 기간과 무관하며, 계획 이행 여부를 뜻하지 않는다."
    >
      최근 소각
    </span>
  );
}

// [파티 결정 2026-07-29] market_fallback 라벨 "전체시장 폴백" → "시장 전체 비교".
// 실측: KSIC sparsity로 peer 버킷이 서지 않아 **전건**이 market_fallback이다(3주째).
// "폴백"은 일시적 강등처럼 읽히지만 현실은 상시 상태다 — 조건부 경고 배지 대신
// 지금 사실인 문장으로 쓴다(소각 배지 "최근 소각" 정정과 같은 계열: 판정이 아니라 사실).
// KSIC sparse 해소는 백로그에 살아 있다 — 라벨 정정이 문제 해결이 아니다.
export function PopulationBasisChip({ basis }: { basis: string | null }) {
  if (!basis) return null;
  let label = "시장 전체 비교";
  let title: string | undefined;
  if (basis.startsWith("sector:")) label = `업종 내 (KSIC ${basis.slice(7)})`;
  else if (basis === "market_fallback") {
    title = "업종(KSIC) 데이터가 희소해 업종 내 비교가 서지 않아, 시장 전체를 모집단으로 비교한 순위다.";
  }
  return <span className="text-[9px] text-gray-400" title={title}>{label}</span>;
}

export function MarketPill({ market }: { market: string | null }) {
  if (!market) return <span className="text-xs text-gray-400">—</span>;
  const kospi = market === "KOSPI";
  return <Pill text={market} bg={kospi ? "#eff6ff" : "#f5f3ff"} fg={kospi ? "#1d4ed8" : "#6d28d9"} />;
}
