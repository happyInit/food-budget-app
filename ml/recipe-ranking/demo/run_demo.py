"""ML 개인화 발표 데모 — 한 명령 재현.

  python demo/run_demo.py            # 실행 → demo/out/results.json + demo/out/report.html
  python demo/run_demo.py --open     # 실행 후 리포트 경로 출력

Layer 1(정량): 페르소나 합성 클릭스트림 → 학습 → 검증셋에서 NDCG@k·MAP·MRR을
              규칙 baseline 대비 lift로 측정.
Layer 2(해석): 페르소나별 고정 후보셋에서 '규칙 순위 → ML 재랭킹' before/after를 실 레시피명으로.

⚠️ 전부 격리·합성. 프로덕션 DB·서버 무접촉. 발표 문구는 "mock 기반 오프라인 검증"으로 정직하게.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # ml/recipe-ranking

from features import FEATURE_COLUMNS, baseline_scores, to_matrix  # noqa: E402
from train import train  # noqa: E402
from evaluate import compare  # noqa: E402
from demo.personas import (  # noqa: E402
    DEMO_PERSONAS, PERSONAS, demo_candidates, make_training_rows,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def _matrix(rows: list[dict]) -> np.ndarray:
    return np.array([[float(r.get(c, 0.0)) for c in FEATURE_COLUMNS] for r in rows], dtype=float)


def _split_by_group(rows: list[dict], val_frac: float = 0.25, seed: int = 0):
    groups = sorted({r["group"] for r in rows})
    rng = np.random.default_rng(seed)
    rng.shuffle(groups)
    n_val = max(1, int(len(groups) * val_frac))
    val_g = set(groups[:n_val])
    train_rows = [r for r in rows if r["group"] not in val_g]
    val_rows = [r for r in rows if r["group"] in val_g]
    return train_rows, val_rows


def layer1_quant(train_rows, val_rows, k: int = 5) -> dict:
    """검증셋 NDCG@k·MAP·MRR — ML vs 규칙 baseline."""
    Xtr, ytr, gtr = to_matrix(train_rows)
    model = train(Xtr, ytr, gtr)
    Xv, yv, gv = to_matrix(val_rows)
    ml_score = model.predict(Xv)
    base_score = baseline_scores(val_rows)   # rule_score만
    cmp = compare(yv, ml_score, base_score, gv, k=k)
    cmp["k"] = k
    cmp["n_val_groups"] = int(len(set(gv.tolist())))
    cmp["n_train_groups"] = int(len(set(gtr.tolist())))
    return model, cmp


def layer2_interpretable(model, pop, top: int = 5) -> list[dict]:
    """페르소나별 규칙 순위 vs ML 순위 before/after(실 레시피명)."""
    demos = []
    for pkey in DEMO_PERSONAS:
        cands = demo_candidates(pkey, pop)
        X = _matrix(cands)
        ml = model.predict(X)
        rule = np.array([c["rule_score"] for c in cands])
        rule_order = [cands[i] for i in np.argsort(-rule, kind="stable")]
        ml_order = [cands[i] for i in np.argsort(-ml, kind="stable")]
        # 취향 매칭 판정(설명용) — user_ing_affinity 높은 것 = 페르소나 취향
        def entry(c):
            return {"name": c["_name"], "tags": c["_tags"],
                    "match": bool(c["user_ing_affinity"] > 0.8)}
        demos.append({
            "persona": PERSONAS[pkey]["label"], "desc": PERSONAS[pkey]["desc"],
            "rule_top": [entry(c) for c in rule_order[:top]],
            "ml_top": [entry(c) for c in ml_order[:top]],
        })
    return demos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true", help="리포트 경로 출력")
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    rows, pop = make_training_rows()
    train_rows, val_rows = _split_by_group(rows)
    model, quant = layer1_quant(train_rows, val_rows, k=args.k)
    demos = layer2_interpretable(model, pop)

    results = {"layer1": quant, "layer2": demos,
               "n_recipes": len({r["_recipe_id"] for r in rows}),
               "personas": [PERSONAS[p]["label"] for p in DEMO_PERSONAS]}

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    from demo.report import render_html
    html_path = os.path.join(OUT, "report.html")
    with open(html_path, "w") as f:
        f.write(render_html(results))

    ml, base = quant["model"], quant["baseline"]
    print(f"[Layer1] NDCG@{args.k}  ML={ml['ndcg@k']:.3f}  baseline={base['ndcg@k']:.3f}  "
          f"lift={quant['ndcg_lift']*100:+.1f}%  (val {quant['n_val_groups']} groups)")
    print(f"         MAP={ml['map@k']:.3f}(base {base['map@k']:.3f})  MRR={ml['mrr']:.3f}(base {base['mrr']:.3f})")
    for d in demos:
        moved = d["ml_top"][0]["name"]
        print(f"[Layer2] {d['persona']}: ML 1순위 = '{moved}'  (규칙 1순위 = '{d['rule_top'][0]['name']}')")
    print(f"→ 리포트: {html_path}")
    print(f"→ 수치:   {os.path.join(OUT, 'results.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
