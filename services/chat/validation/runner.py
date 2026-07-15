"""검증 실행기 — 풀에서 랜덤 30개 샘플 → 서비스 호출 → 정답 라벨 대조 → 누적 기록.

사용:
  python validation/runner.py --label "iter2-오프토픽차단" --note "날씨/주식 등 오프토픽 불용어 추가" [--n 30] [--seed 42]

동작:
  1. pool.POOL에서 n개 층화(카테고리 비율 유지) 랜덤 샘플
  2. localhost:8001/chat 호출 → answered = not unanswered
  3. 정답 판정: answer→응답=정답 / refuse→거절=정답 / gray→채점제외
  4. runs.json에 append (단일 진실원) → VALIDATION_LOG.md 재렌더
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pool import POOL  # noqa: E402

HERE = Path(__file__).parent
RUNS_JSON = HERE / "runs.json"
LOG_MD = HERE / "VALIDATION_LOG.md"
ENDPOINT = "http://localhost:8001/chat"
KST = timezone(timedelta(hours=9))


def _sample(n: int, seed: int) -> list[tuple[str, str, str]]:
    """카테고리 비율을 최대한 유지하며 n개 샘플(층화). 부족하면 전체에서 보충."""
    rng = random.Random(seed)
    by_cat: dict[str, list] = defaultdict(list)
    for item in POOL:
        by_cat[item[1]].append(item)
    cats = list(by_cat)
    picked: list = []
    # 카테고리별 비례 할당
    for cat in cats:
        share = max(1, round(n * len(by_cat[cat]) / len(POOL)))
        picked += rng.sample(by_cat[cat], min(share, len(by_cat[cat])))
    rng.shuffle(picked)
    if len(picked) > n:
        picked = picked[:n]
    elif len(picked) < n:
        rest = [x for x in POOL if x not in picked]
        picked += rng.sample(rest, min(n - len(picked), len(rest)))
    return picked


def _ask(message: str) -> tuple[bool, str, str]:
    body = json.dumps({"message": message}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        answered = not data.get("unanswered", True)
        return answered, data.get("reply", "").replace("\n", " / "), "ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"ERROR: {exc}", "err"


def run(label: str, note: str, n: int, seed: int) -> dict:
    sample = _sample(n, seed)
    results = []
    for query, category, expected in sample:
        answered, reply, status = _ask(query)
        if expected == "gray":
            correct = None
        else:
            correct = (expected == "answer" and answered) or (expected == "refuse" and not answered)
        results.append({
            "query": query, "category": category, "expected": expected,
            "answered": answered, "reply": reply, "correct": correct, "status": status,
        })
    return {
        "label": label, "note": note, "n": n, "seed": seed,
        "timestamp": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "results": results,
    }


def _load_runs() -> list[dict]:
    if RUNS_JSON.exists():
        return json.loads(RUNS_JSON.read_text(encoding="utf-8"))
    return []


def _cat_rate(results: list[dict]) -> dict[str, tuple[int, int]]:
    """카테고리 → (정답수, 채점대상수). gray 제외."""
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in results:
        if r["correct"] is None:
            continue
        agg[r["category"]][1] += 1
        if r["correct"]:
            agg[r["category"]][0] += 1
    return {k: (v[0], v[1]) for k, v in agg.items()}


def _overall(results: list[dict]) -> tuple[int, int]:
    scored = [r for r in results if r["correct"] is not None]
    return sum(1 for r in scored if r["correct"]), len(scored)


def render(runs: list[dict]) -> str:
    lines: list[str] = []
    lines.append("# Chat Service 검증 로그 (RAG 챗봇)")
    lines.append("")
    lines.append("> 자동 생성 — `python validation/runner.py`로 갱신. 풀·라벨 근거는 `validation/pool.py`.")
    lines.append("> 정답 기준: **answer**=응답해야 정답 · **refuse**=거절('모르겠어요')해야 정답 · **gray**=채점 제외(모호 요청).")
    lines.append("")

    # ── 개선 흐름 요약 (iteration별 정답률 추이) ──
    lines.append("## 개선 흐름 요약")
    lines.append("")
    all_cats = sorted({r["category"] for run in runs for r in run["results"] if r["correct"] is not None})
    header = ["#", "iteration", "개선 내용", "전체 정답률"] + [c.split("_", 1)[-1] for c in all_cats]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for i, run in enumerate(runs, 1):
        oc, ot = _overall(run["results"])
        rate = f"{oc}/{ot} ({round(100*oc/ot) if ot else 0}%)"
        cr = _cat_rate(run["results"])
        cells = [str(i), run["label"], run["note"], rate]
        for c in all_cats:
            if c in cr:
                got, tot = cr[c]
                cells.append(f"{got}/{tot}")
            else:
                cells.append("·")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("> 카테고리 셀 = 정답/채점대상. 랜덤 샘플이라 iteration마다 카테고리별 문항 수는 다를 수 있음 — 비율로 볼 것.")
    lines.append("")

    # ── iteration별 상세 ──
    for i, run in enumerate(runs, 1):
        oc, ot = _overall(run["results"])
        lines.append("---")
        lines.append("")
        lines.append(f"## Iteration {i} — {run['label']}")
        lines.append("")
        lines.append(f"- **시각**: {run['timestamp']} · **샘플**: {run['n']}문항 (seed={run['seed']})")
        lines.append(f"- **개선 내용**: {run['note']}")
        lines.append(f"- **전체 정답률**: {oc}/{ot} ({round(100*oc/ot) if ot else 0}%) · gray {sum(1 for r in run['results'] if r['correct'] is None)}건 제외")
        lines.append("")
        lines.append("| 질문 | 카테고리 | 기대 | 실제 | 판정 | 응답 요약 |")
        lines.append("|---|---|---|---|---|---|")
        for r in run["results"]:
            q = r["query"].strip() or "(빈 문자열)"
            if len(q) > 40:
                q = q[:38] + "…"
            actual = "응답" if r["answered"] else "거절"
            if r["correct"] is None:
                verdict = "—"
            else:
                verdict = "✅" if r["correct"] else "❌"
            reply = r["reply"]
            if len(reply) > 55:
                reply = reply[:53] + "…"
            exp_ko = {"answer": "응답", "refuse": "거절", "gray": "gray"}[r["expected"]]
            lines.append(f"| {q} | {r['category']} | {exp_ko} | {actual} | {verdict} | {reply} |")
        lines.append("")
        # 오답 분석 힌트
        wrong = [r for r in run["results"] if r["correct"] is False]
        if wrong:
            lines.append(f"**오답 {len(wrong)}건:**")
            for r in wrong:
                lines.append(f"- `{r['query'].strip() or '(빈 문자열)'}` (기대={r['expected']}) → {r['reply'][:70]}")
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--note", required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()
    seed = args.seed if args.seed is not None else random.randrange(1_000_000)

    run_rec = run(args.label, args.note, args.n, seed)
    runs = _load_runs()
    runs.append(run_rec)
    RUNS_JSON.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    LOG_MD.write_text(render(runs), encoding="utf-8")

    oc, ot = _overall(run_rec["results"])
    print(f"[{args.label}] 전체 정답률 {oc}/{ot} ({round(100*oc/ot) if ot else 0}%), seed={seed}")
    for cat, (got, tot) in sorted(_cat_rate(run_rec["results"]).items()):
        print(f"  {cat}: {got}/{tot}")


if __name__ == "__main__":
    main()
