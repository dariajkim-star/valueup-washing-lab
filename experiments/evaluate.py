"""평가 하네스 — 규칙 · 어휘 · 임베딩을 **같은 조건**에서 비교한다.

설계 결정 네 가지와 그 이유:

■ 1. 정답은 골드셋이지 `valueup_plan.body_signal`이 아니다
    DB 컬럼은 `classify_body`의 출력이다. 그것을 정답으로 쓰면 규칙 시스템의 점수는
    **정의상 1.0**이고 아무것도 측정하지 못한다. 이 하네스는 사람이 채운
    `gold_packet_blind.csv`만 정답으로 받는다. 아직 안 채워졌으면 `--dry`로
    자기검증만 돌린다(규칙이 1.0을 받는지 확인 — 받아야 하네스가 정상이다).

■ 2. 회사 단위 분할 — 같은 회사가 train/test에 갈리면 누수다
    한 회사가 여러 해에 걸쳐 거의 같은 문장으로 공시한다. 행 단위로 섞으면 모델이
    '의미'가 아니라 '그 회사 문체'를 외우고, 점수가 부풀려진다. 그래서 `corp_code`를
    그룹으로 묶어 통째로 한 폴드에 넣는다(StratifiedGroupKFold와 같은 취지).

■ 3. 반복 K-fold, 단일 숫자 금지
    소수 클래스가 `refiling` 19 · `other_metric` 16이라 폴드당 3~4건이다. 이 규모에서
    macro-F1 한 개는 시드 운에 좌우된다. 시드를 바꿔 R회 반복하고 **평균±표준편차**로
    보고한다. 표준편차가 차이보다 크면 "이겼다"고 말하지 않는다.

■ 4. 어휘 baseline을 임베딩보다 먼저 둔다
    char n-gram + 로지스틱은 의존성이 없고 몇 초면 끝난다. **이걸 못 이기는 임베딩은
    쓸 이유가 없다.** 규칙 → 어휘 → 임베딩 순으로 올라가며, 각 단계가 앞 단계를
    이겨야만 다음 복잡도가 정당화된다.

의존성: numpy만. 문장 임베딩 시스템은 sentence-transformers가 있을 때만 켜지고,
없으면 그 시스템만 건너뛴다(하네스는 계속 돈다).

실행:
    .venv\\Scripts\\python.exe experiments\\evaluate.py --dry          # 하네스 자기검증
    .venv\\Scripts\\python.exe experiments\\evaluate.py                 # 골드 라벨로 실측
    .venv\\Scripts\\python.exe experiments\\evaluate.py --st-model BAAI/bge-m3
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analysis.plan_signals import classify_body, declares_no_attachment  # noqa: E402
from experiments.preprocess import clean, segments  # noqa: E402

OUT = ROOT / "experiments" / "out"
CONTENT_CLASSES = ("no_targets", "refiling", "other_metric")  # 축=0 구간에 나타나는 값
ATT_CLASSES = ("0", "1")


# ── 데이터 ──────────────────────────────────────────────────────────────────

def _read_labels(path: Path) -> dict[str, dict]:
    """별도 기입 파일(`gold_labels.csv`)을 읽어 plan_id → 라벨로. 없으면 빈 사전."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig") as f:
        return {str(r["plan_id"]).strip(): r for r in csv.DictReader(f) if r.get("plan_id")}


def load(dry: bool) -> list[dict]:
    """골드 패킷 + DB 원문. dry면 규칙 출력을 임시 정답으로 쓴다(측정 아님).

    라벨은 패킷이 아니라 **별도 파일 `gold_labels.csv`**에서 읽는다. 패킷에 직접 쓰면
    Excel이 형식을 바꾸거나 저장이 누락되는 사고가 난다. 패킷은 원문 전용이다.
    (호환: 패킷 안에 라벨이 채워져 있으면 그것도 받되, 별도 파일이 우선한다.)
    """
    packet = OUT / "gold_packet_blind.csv"
    if not packet.exists():
        raise SystemExit(f"패킷이 없다: {packet}\n먼저 body_signal_baseline.py를 돌려라.")

    with packet.open(encoding="utf-8-sig") as f:
        gold = {r["plan_id"]: r for r in csv.DictReader(f)}

    side = _read_labels(OUT / "gold_labels.csv")
    for pid, lab in side.items():
        if pid in gold:
            for col in ("gold_body_signal", "gold_attachment_absent"):
                if (lab.get(col) or "").strip():
                    gold[pid][col] = lab[col]

    con = sqlite3.connect(ROOT / "valueup.db")
    con.row_factory = sqlite3.Row
    db = {str(r["plan_id"]): dict(r) for r in con.execute("SELECT * FROM valueup_plan")}
    con.close()

    rows = []
    skipped = Counter()
    for pid, g in gold.items():
        r = db.get(pid)
        if r is None:
            continue
        y_content = (g.get("gold_body_signal") or "").strip()
        y_att = (g.get("gold_attachment_absent") or "").strip()
        if dry:
            y_content = r["body_signal"]
            y_att = str(int(bool(r["attachment_absent"])))
        if not y_content or not y_att:
            skipped["미기입"] += 1
            continue
        # 학습 모수에서 빼는 값 — 라벨링 기준서 §2-A/§2-C
        if y_content in ("parser_miss", "notice"):
            skipped[y_content] += 1
            continue
        # 오타를 새 클래스로 받아들이면 지표가 조용히 망가진다
        if y_content not in CONTENT_CLASSES:
            skipped[f"알 수 없는 값 '{y_content}'"] += 1
            continue
        if y_att not in ATT_CLASSES:
            skipped[f"알 수 없는 첨부값 '{y_att}'"] += 1
            continue
        rows.append({
            "plan_id": pid,
            "group": r.get("corp_code") or pid,   # 회사 없으면 자기 자신이 그룹
            "row": r,
            "text": clean(r.get("raw_text")),
            "segs": segments(r.get("raw_text")),
            "y_content": y_content,
            "y_att": y_att,
        })

    if skipped:
        print("\n[제외 내역] " + " · ".join(f"{k} {v}건" for k, v in skipped.items()))
        if any(k.startswith("알 수 없는") for k in skipped):
            print("  ↑ 오타로 보인다. gold_labels.csv를 고치고 다시 돌려라.")
    return rows


# ── 폴드 분할 (회사 단위 + 층화) ────────────────────────────────────────────

def group_folds(rows: list[dict], y_key: str, k: int, seed: int) -> list[np.ndarray]:
    """그룹을 통째로 폴드에 배정하되, 폴드별 클래스 분포를 최대한 고르게 한다.

    큰 그룹부터 '그 그룹의 주 클래스가 가장 부족한 폴드'로 보내는 탐욕 배정.
    희귀 클래스가 한 폴드에 몰려 다른 폴드의 recall이 정의되지 않는 사고를 막는다.
    """
    rng = np.random.default_rng(seed)
    by_group: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_group[r["group"]].append(i)

    groups = list(by_group)
    rng.shuffle(groups)
    groups.sort(key=lambda g: -len(by_group[g]))

    classes = sorted({r[y_key] for r in rows})
    fold_counts = [Counter() for _ in range(k)]
    folds: list[list[int]] = [[] for _ in range(k)]

    for g in groups:
        idx = by_group[g]
        cnt = Counter(rows[i][y_key] for i in idx)
        main_cls = cnt.most_common(1)[0][0]
        # 주 클래스가 가장 적은 폴드 → 동률이면 전체가 작은 폴드
        best = min(range(k), key=lambda j: (fold_counts[j][main_cls], sum(fold_counts[j].values())))
        folds[best].extend(idx)
        fold_counts[best].update(cnt)

    assert sum(len(f) for f in folds) == len(rows)
    del classes
    return [np.array(sorted(f), dtype=int) for f in folds]


# ── 지표 ────────────────────────────────────────────────────────────────────

def scores(y_true: list[str], y_pred: list[str], classes: tuple[str, ...]) -> dict:
    """macro-F1 + 클래스별 recall/precision/support. 분모 0은 nan으로 두고 평균에서 뺀다."""
    out = {"per_class": {}}
    f1s = []
    for c in classes:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == c and p != c)
        sup = tp + fn
        rec = tp / sup if sup else float("nan")
        pre = tp / (tp + fp) if (tp + fp) else float("nan")
        f1 = (2 * pre * rec / (pre + rec)) if (pre and rec and pre + rec > 0) else (
            0.0 if sup else float("nan"))
        out["per_class"][c] = {"recall": rec, "precision": pre, "f1": f1, "support": sup}
        if sup:
            f1s.append(0.0 if np.isnan(f1) else f1)
    out["macro_f1"] = float(np.mean(f1s)) if f1s else float("nan")
    out["accuracy"] = sum(1 for t, p in zip(y_true, y_pred) if t == p) / max(1, len(y_true))
    return out


# ── 특징: char n-gram 해싱 (의존성 0) ───────────────────────────────────────

_NONWORD = re.compile(r"\s+")


def hash_features(texts: list[str], dim: int = 2 ** 14, ngrams=(2, 3, 4)) -> np.ndarray:
    """char n-gram 해싱 + L2 정규화. 한국어 형태소 분석기 없이 쓰는 표준 어휘 baseline.

    내장 `hash()`는 문자열에 대해 프로세스마다 값이 달라진다(PYTHONHASHSEED). 실행할
    때마다 특징 공간이 바뀌면 재현이 불가능하므로 crc32를 쓴다.
    """
    X = np.zeros((len(texts), dim), dtype=np.float32)
    for i, t in enumerate(texts):
        s = _NONWORD.sub(" ", t)
        for n in ngrams:
            for j in range(len(s) - n + 1):
                X[i, zlib.crc32(s[j:j + n].encode("utf-8")) % dim] += 1.0
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    return X / np.maximum(norms, 1e-9)


# ── 분류기: 다항 로지스틱 (numpy, 클래스 가중) ──────────────────────────────

class LogReg:
    """소수 클래스 가중을 켠 다항 로지스틱. 결정론적(고정 반복·고정 초기값)."""

    def __init__(self, l2: float = 1e-3, lr: float = 1.0, iters: int = 400):
        self.l2, self.lr, self.iters = l2, lr, iters

    def fit(self, X: np.ndarray, y: list[str]) -> "LogReg":
        self.classes_ = sorted(set(y))
        idx = {c: i for i, c in enumerate(self.classes_)}
        Y = np.zeros((len(y), len(self.classes_)), dtype=np.float32)
        for i, c in enumerate(y):
            Y[i, idx[c]] = 1.0
        # 역빈도 가중 — refiling/other_metric이 다수 클래스에 묻히지 않게
        cnt = Counter(y)
        w = np.array([len(y) / (len(self.classes_) * cnt[c]) for c in y], dtype=np.float32)[:, None]

        Xb = np.hstack([X, np.ones((X.shape[0], 1), dtype=np.float32)])
        W = np.zeros((Xb.shape[1], len(self.classes_)), dtype=np.float32)
        for _ in range(self.iters):
            Z = Xb @ W
            Z -= Z.max(axis=1, keepdims=True)
            P = np.exp(Z)
            P /= P.sum(axis=1, keepdims=True)
            G = Xb.T @ (w * (P - Y)) / len(y) + self.l2 * W
            W -= self.lr * G
        self.W = W
        return self

    def predict(self, X: np.ndarray) -> list[str]:
        Xb = np.hstack([X, np.ones((X.shape[0], 1), dtype=np.float32)])
        return [self.classes_[i] for i in np.argmax(Xb @ self.W, axis=1)]


# ── 시스템들 ────────────────────────────────────────────────────────────────

def signal_section(r: dict) -> str:
    """마지막 절 — 실측상 판정 신호의 216/226이 여기 있다(preprocess §4).

    '전체 문서'와 비교하기 위한 절제(ablation) 입력. 이 단순 규칙을 못 이기면
    MIL이든 파인튜닝이든 복잡도가 정당화되지 않는다.
    """
    segs = r["segs"]
    return segs[-1][1] if segs else r["text"]


def sys_rule(train, test, task):
    """규칙 baseline — 학습하지 않는다. train은 받지만 쓰지 않는다."""
    if task == "content":
        return [classify_body(r["row"].get("raw_text"), r["row"]).kind for r in test]
    return [str(int(declares_no_attachment(r["row"].get("raw_text")))) for r in test]


def _lr_system(featurize):
    def run(train, test, task):
        key = "y_content" if task == "content" else "y_att"
        Xtr = featurize([r for r in train])
        Xte = featurize([r for r in test])
        return LogReg().fit(Xtr, [r[key] for r in train]).predict(Xte)
    return run


sys_char_full = _lr_system(lambda rs: hash_features([r["text"] for r in rs]))
sys_char_tail = _lr_system(lambda rs: hash_features([signal_section(r) for r in rs]))


def make_st_system(model_name: str, tail: bool):
    """frozen 문장 임베딩 + 로지스틱. sentence-transformers가 있을 때만 만들어진다."""
    from sentence_transformers import SentenceTransformer  # 지연 import

    model = SentenceTransformer(model_name)
    cache: dict[str, np.ndarray] = {}

    def featurize(rs):
        texts = [(signal_section(r) if tail else r["text"]) for r in rs]
        todo = [t for t in texts if t not in cache]
        if todo:
            vecs = model.encode(todo, normalize_embeddings=True, show_progress_bar=False)
            cache.update(dict(zip(todo, vecs)))
        return np.vstack([cache[t] for t in texts]).astype(np.float32)

    return _lr_system(featurize)


# ── 평가 루프 ───────────────────────────────────────────────────────────────

def evaluate(rows, systems, task, classes, k, repeats):
    key = "y_content" if task == "content" else "y_att"
    acc: dict[str, list[dict]] = {name: [] for name in systems}

    for rep in range(repeats):
        folds = group_folds(rows, key, k, seed=1000 + rep)
        for f in range(k):
            te_idx = folds[f]
            tr_idx = np.concatenate([folds[j] for j in range(k) if j != f])
            train = [rows[i] for i in tr_idx]
            test = [rows[i] for i in te_idx]
            if not test:
                continue
            y_true = [r[key] for r in test]
            for name, fn in systems.items():
                acc[name].append(scores(y_true, fn(train, test, task), classes))
    return acc


def report(title, acc, classes):
    print(f"\n{'=' * 62}\n{title}\n{'=' * 62}")
    print(f"{'시스템':<22}{'macro-F1':>18}{'accuracy':>14}")
    for name, rs in acc.items():
        m = [r["macro_f1"] for r in rs if not np.isnan(r["macro_f1"])]
        a = [r["accuracy"] for r in rs]
        print(f"{name:<22}{np.mean(m):>10.3f} ±{np.std(m):<6.3f}{np.mean(a):>14.3f}")

    print(f"\n{'클래스별 recall (평균±표준편차)':<22}")
    print(f"{'시스템':<22}" + "".join(f"{c:>18}" for c in classes))
    for name, rs in acc.items():
        cells = []
        for c in classes:
            v = [r["per_class"][c]["recall"] for r in rs
                 if not np.isnan(r["per_class"][c]["recall"])]
            cells.append(f"{np.mean(v):>10.3f} ±{np.std(v):<6.3f}" if v else f"{'n/a':>18}")
        print(f"{name:<22}" + "".join(cells))

    sup = Counter()
    for r in acc[next(iter(acc))]:
        for c in classes:
            sup[c] += r["per_class"][c]["support"]
    print("\n  폴드 누적 support: " + " · ".join(f"{c}={sup[c]}" for c in classes))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true",
                    help="골드 대신 규칙 출력을 정답으로 — 하네스 자기검증용(측정 아님)")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--st-model", default=None, help="예: BAAI/bge-m3 (sentence-transformers 필요)")
    args = ap.parse_args()

    rows = load(args.dry)
    if args.dry:
        print("!" * 62)
        print("!! --dry: 정답이 규칙 출력이다. 이 숫자는 측정이 아니라 하네스 자기검증이다.")
        print("!!        규칙 시스템이 1.000을 받아야 정상이고, 그 외 시스템의 점수는")
        print("!!        '규칙을 얼마나 모사하는가'일 뿐 성능이 아니다.")
        print("!" * 62)
    if not rows:
        raise SystemExit("골드 라벨이 비어 있다. 패킷의 gold_* 열을 채우거나 --dry로 돌려라.")

    print(f"\n표본 {len(rows)}건 · 회사(그룹) {len({r['group'] for r in rows})}개 "
          f"· {args.folds}-fold × {args.repeats}회 반복")
    print(f"내용 라벨 분포   : {dict(Counter(r['y_content'] for r in rows))}")
    print(f"첨부 라벨 분포   : {dict(Counter(r['y_att'] for r in rows))}")

    systems = {
        "규칙(기존)": sys_rule,
        "char n-gram 전체": sys_char_full,
        "char n-gram 마지막절": sys_char_tail,
    }
    if args.st_model:
        try:
            systems[f"frozen {args.st_model} 전체"] = make_st_system(args.st_model, tail=False)
            systems[f"frozen {args.st_model} 마지막절"] = make_st_system(args.st_model, tail=True)
        except ImportError:
            print("\n[건너뜀] sentence-transformers 미설치 — 임베딩 시스템 없이 진행한다.")
            print("         설치: .venv\\Scripts\\pip install sentence-transformers")

    content_classes = tuple(sorted({r["y_content"] for r in rows}))
    report("과제 A · 내용 유형 (axis_targets는 규칙이 상위에서 확정 → 여기 없음)",
           evaluate(rows, systems, "content", content_classes, args.folds, args.repeats),
           content_classes)
    report("과제 B · 첨부 부존재 선언 (직교 이진 축)",
           evaluate(rows, systems, "att", ATT_CLASSES, args.folds, args.repeats),
           ATT_CLASSES)

    print("\n읽는 법: 표준편차가 시스템 간 차이보다 크면 '이겼다'고 말하지 않는다.")
    print("         소수 클래스 recall이 macro-F1보다 먼저다 — 그게 규칙이 놓친 지점이다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
