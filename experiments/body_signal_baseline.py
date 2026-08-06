"""body_signal 학습 실험의 **0번 단계** — 규칙 baseline 고정 + 골드셋 시드 추출.

왜 이 스크립트가 "규칙의 F1을 잰다"가 아닌가:
    `valueup_plan.body_signal`은 **사람이 매긴 정답이 아니라 `classify_body`가 뱉은 출력**이다.
    이걸 y로 놓고 무엇을 학습시키든 규칙의 증류일 뿐이고 macro-F1은 정의상 1.0에 수렴한다.
    비교 대상이 없는 지표는 지표가 아니다. 그래서 여기서 하는 일은 두 가지다.

    (A) 재현성 검증 — DB에 굳은 라벨이 **지금 코드로 다시 나오는가**.
        어긋나면 그 뒤의 모든 측정이 무의미하므로 여기가 첫 관문이다.
        (why-missing의 "상위 변경 시 하위 미재계산 = 실패" 계약과 같은 계열)

    (B) 골드셋 시드 — 사람이 읽고 라벨링할 층화 표본을 뽑는다. 규칙 라벨은 **패킷에서 가린다**
        (blind). 읽는 사람이 규칙 답을 먼저 보면 앵커링돼서 규칙의 오류를 그대로 승인한다.
        정답 키는 별도 파일로 나가고, 사람 라벨이 채워진 뒤에 합쳐서 비교한다.

측정 대상 모수에 대하여:
    `classify_body`의 첫 분기는 `disclosed_axis_count(targets) > 0`이다 — **본문을 보지 않는다.**
    파싱된 축이 하나라도 있으면 axis_targets로 확정된다(309건). 이 구간은 텍스트 모델이
    배울 것이 없으므로, 인코더가 실제로 겨루는 모수는 **축이 0인 나머지**다. 스크립트는
    두 모수를 나눠 보고한다.

attachment_absent에 대하여:
    body_signal과 **직교**한다(plan_selection.py 주석 — 부존재 선언 212건 중 102건이
    axis_targets와 공존). 한 축에 합쳐 5분류로 만들면 반드시 샌다. 여기서도 따로 센다.

실행:
    .venv\\Scripts\\python.exe experiments\\body_signal_baseline.py
    .venv\\Scripts\\python.exe experiments\\body_signal_baseline.py --sample 120 --seed 20260805
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analysis.plan_selection import AXIS_TARGETS, disclosed_axis_count  # noqa: E402
from app.analysis.plan_signals import classify_body, declares_no_attachment  # noqa: E402
from experiments.preprocess import clean, is_notice, segments  # noqa: E402

OUT_DIR = ROOT / "experiments" / "out"
CLASSES = ("axis_targets", "no_targets", "refiling", "other_metric")


# ── 적재 ────────────────────────────────────────────────────────────────────

def load_rows(db_path: Path) -> list[dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM valueup_plan")]
    con.close()
    return rows


# ── (A) 재현성 검증 ─────────────────────────────────────────────────────────

def replay(rows: list[dict]) -> dict:
    """저장된 라벨 vs 지금 코드가 다시 낸 라벨.

    classify_body는 (본문, 목표 매핑)을 받는다. 목표 매핑은 행 자체다 —
    disclosed_axis_count가 target_* / period_* / buyback_planned 키를 읽는다.
    """
    sig_mismatch, att_mismatch = [], []
    confusion: Counter = Counter()

    for r in rows:
        got = classify_body(r.get("raw_text"), r).kind
        stored = r.get("body_signal")
        confusion[(stored, got)] += 1
        if stored != got:
            sig_mismatch.append({"plan_id": r["plan_id"], "stored": stored, "replayed": got})

        got_att = declares_no_attachment(r.get("raw_text"))
        stored_att = r.get("attachment_absent")
        if stored_att is not None and bool(stored_att) != got_att:
            att_mismatch.append(
                {"plan_id": r["plan_id"], "stored": bool(stored_att), "replayed": got_att}
            )

    return {
        "n": len(rows),
        "signal_mismatch": sig_mismatch,
        "attachment_mismatch": att_mismatch,
        "confusion": confusion,
    }


# ── 모수 분해 ───────────────────────────────────────────────────────────────

def partition(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """(규칙 확정, 예고 제외, 인코더가 겨룰 구간).

    1) 파싱된 축이 있으면 axis_targets로 확정된다 — 본문을 보지 않으므로 학습 대상 아님.
    2) 예고(안내공시)는 머리말 문자열로 100% 갈린다 — 남겨두면 쉬운 케이스가 27%를
       차지해 지표가 부풀려진다(labeling-guide §2-A).
    남은 것이 실제 모수다.
    """
    decided = [r for r in rows if disclosed_axis_count(r) > 0]
    rest = [r for r in rows if disclosed_axis_count(r) == 0]
    notice = [r for r in rest if is_notice(r.get("raw_text"))]
    contested = [r for r in rest if not is_notice(r.get("raw_text"))]
    return decided, notice, contested


# ── 문단 통계 (pooling 설계 근거) ───────────────────────────────────────────

def text_stats(rows: list[dict]) -> dict:
    """mean pooling이 왜 위험한지를 숫자로 남긴다 — 신호 절 1개 / 전체 절 N개의 비율.

    길이는 **정제본 기준**이다. 원문의 절반은 XForms 스타일시트라(preprocess 실측 50.7%)
    원문 길이로 토큰 예산을 잡으면 두 배로 잡게 된다.
    """
    lens = sorted(len(clean(r.get("raw_text"))) for r in rows)
    segs = sorted(len(segments(r.get("raw_text"))) for r in rows)

    def pct(xs: list[int], q: float) -> float:
        return xs[min(len(xs) - 1, int(len(xs) * q))] if xs else 0.0

    return {
        "chars_p50": pct(lens, 0.50),
        "chars_p90": pct(lens, 0.90),
        "chars_max": lens[-1] if lens else 0,
        "segs_p50": pct(segs, 0.50),
        "segs_p90": pct(segs, 0.90),
        "segs_max": segs[-1] if segs else 0,
    }


# ── (B) 골드셋 시드 ─────────────────────────────────────────────────────────

def build_packet(rows: list[dict], n: int, seed: int) -> list[dict]:
    """층화 표본. 소수 클래스(refiling 19 / other_metric 16)는 **전수**로 넣는다.

    5-fold에서 fold당 3~4건이 되는 규모라, 표집으로 더 줄이면 측정 자체가 성립하지 않는다.
    다수 클래스는 남은 정원을 비율대로 나눠 채운다.
    """
    rng = random.Random(seed)
    by_class: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_class[r.get("body_signal") or "NULL"].append(r)

    small = [c for c in by_class if len(by_class[c]) <= 30]
    picked: list[dict] = []
    for c in small:
        picked.extend(by_class[c])

    remaining = max(0, n - len(picked))
    big = {c: v for c, v in by_class.items() if c not in small}
    total_big = sum(len(v) for v in big.values()) or 1
    for c, v in big.items():
        k = min(len(v), round(remaining * len(v) / total_big))
        picked.extend(rng.sample(v, k))

    rng.shuffle(picked)  # 읽는 순서에서 클래스가 드러나지 않게
    return picked


def write_labels_template(picked: list[dict]) -> tuple[Path, bool]:
    """라벨 기입용 별도 파일. **이미 있으면 절대 덮어쓰지 않는다.**

    패킷 자체에 기입하면 Excel이 형식을 바꿔 저장하거나 저장이 누락되는 사고가 난다
    (2026-08-06 실제 발생). 패킷은 읽기 전용으로 두고 라벨만 여기 적는다 —
    plan_id를 미리 채워두므로 두 열만 입력하면 된다.
    """
    path = OUT_DIR / "gold_labels.csv"
    if path.exists():
        return path, False  # 사람이 채운 파일을 재생성으로 날리지 않는다
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["plan_id", "gold_body_signal", "gold_attachment_absent", "note"])
        for r in picked:
            w.writerow([r["plan_id"], "", "", ""])
    return path, True


def write_packet(picked: list[dict]) -> tuple[Path, Path]:
    """블라인드 패킷과 정답 키를 분리해서 쓴다.

    패킷에는 규칙 라벨이 없다. 사람이 규칙 답을 먼저 보면 규칙의 오류를 승인하게 된다
    (why-missing holdout-blind-reading-packet과 같은 이유).
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    packet_path = OUT_DIR / "gold_packet_blind.csv"
    key_path = OUT_DIR / "gold_packet_key.csv"

    with packet_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["plan_id", "corp_code", "disclosure_date",
             "gold_body_signal", "gold_attachment_absent", "note", "n_sections", "text"]
        )
        for r in picked:
            # 스타일시트를 벗긴 정제본을 싣는다 — 원문의 절반이 CSS라 그대로 두면 읽을 수 없다.
            w.writerow([r["plan_id"], r.get("corp_code"), r.get("disclosure_date"),
                        "", "", "", len(segments(r.get("raw_text"))),
                        clean(r.get("raw_text"))])

    with key_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["plan_id", "rule_body_signal", "rule_attachment_absent"])
        for r in picked:
            w.writerow([r["plan_id"], r.get("body_signal"),
                        int(bool(r.get("attachment_absent"))) if r.get("attachment_absent") is not None else ""])

    return packet_path, key_path


# ── 보고 ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "valueup.db"))
    ap.add_argument("--sample", type=int, default=120, help="골드 패킷 목표 건수")
    ap.add_argument("--seed", type=int, default=20260805)
    ap.add_argument("--no-packet", action="store_true", help="재현성 검증만")
    args = ap.parse_args()

    rows = load_rows(Path(args.db))
    print(f"# valueup_plan: {len(rows)}건\n")

    # (A)
    rep = replay(rows)
    ok_sig = not rep["signal_mismatch"]
    ok_att = not rep["attachment_mismatch"]
    n_sig = len(rep["signal_mismatch"])
    n_att = len(rep["attachment_mismatch"])
    print("## A. 규칙 재현성")
    print("  body_signal        : " + ("재현 OK" if ok_sig else f"불일치 {n_sig}건"))
    print("  attachment_absent  : " + ("재현 OK" if ok_att else f"불일치 {n_att}건"))
    for m in rep["signal_mismatch"][:10]:
        print(f"    - plan {m['plan_id']}: 저장 {m['stored']} → 재실행 {m['replayed']}")
    for m in rep["attachment_mismatch"][:10]:
        print(f"    - plan {m['plan_id']}: 저장 {m['stored']} → 재실행 {m['replayed']}")
    print()

    # 모수 분해
    decided, notice, contested = partition(rows)
    print("## B. 모수 분해 (인코더가 실제로 겨룰 구간)")
    print(f"  규칙 확정 (축>0 → axis_targets): {len(decided)}건  — 본문을 보지 않음, 학습 대상 아님")
    print(f"  예고(안내공시) 제외            : {len(notice)}건  — 머리말로 100% 갈림, 지표 부풀림 방지")
    print(f"  인코더 담당 (축=0, 예고 제외)   : {len(contested)}건")
    dist = Counter(r.get("body_signal") for r in contested)
    for c, k in dist.most_common():
        print(f"      {c:<14} {k:>4}")
    print()

    print("## C. attachment_absent (직교 축 — 별도 head)")
    joint = Counter((r.get("body_signal"), bool(r.get("attachment_absent"))) for r in rows)
    print(f"  {'body_signal':<16}{'첨부부존재=1':>12}{'=0':>8}")
    for c in CLASSES:
        print(f"  {c:<16}{joint[(c, True)]:>12}{joint[(c, False)]:>8}")
    print("  → 한 축에 합치면 위 표의 첫 행(axis_targets & 부존재)이 통째로 사라진다.\n")

    print("## D. 정제 본문 길이·절 통계 (pooling 설계 근거)")
    ts = text_stats(contested)
    print(f"  글자수(정제)  p50={ts['chars_p50']:.0f}  p90={ts['chars_p90']:.0f}  max={ts['chars_max']}")
    print(f"  절 개수       p50={ts['segs_p50']:.0f}  p90={ts['segs_p90']:.0f}  max={ts['segs_max']}")
    print("  → 판정 근거는 통상 절 1개. mean pooling은 나머지 절에 희석된다(max/attention 권장).\n")

    if not args.no_packet:
        picked = build_packet(contested, args.sample, args.seed)
        p, k = write_packet(picked)
        lab, created = write_labels_template(picked)
        print("## E. 골드셋 시드 (사람 라벨링용)")
        print(f"  대상 모수 : 축=0·예고제외 {len(contested)}건 중 {len(picked)}건 표집(소수 클래스 전수)")
        print(f"  블라인드  : {p}   ← 읽기 전용(원문)")
        print(f"  기입 파일 : {lab}   ← {'새로 만듦' if created else '이미 있어 보존함'}")
        print(f"  정답 키   : {k}")
        print("  → 패킷의 gold_* 열을 사람이 채운 뒤, 키와 합쳐 규칙의 실제 정확도를 처음 측정한다.")

        (OUT_DIR / "baseline_summary.json").write_text(
            json.dumps(
                {
                    "n_total": len(rows),
                    "n_rule_decided": len(decided),
                    "n_notice_excluded": len(notice),
                    "n_contested": len(contested),
                    "contested_dist": dict(dist),
                    "replay_signal_mismatch": len(rep["signal_mismatch"]),
                    "replay_attachment_mismatch": len(rep["attachment_mismatch"]),
                    "text_stats": ts,
                    "packet_n": len(picked),
                    "seed": args.seed,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return 0 if (ok_sig and ok_att) else 1


if __name__ == "__main__":
    raise SystemExit(main())
