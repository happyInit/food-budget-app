"""스캐폴드 단위·통합 테스트 — numpy/sklearn만으로 end-to-end 검증(실데이터 무관).

핵심: 합성 데이터에서 **ML(모든 피처)이 규칙 baseline(rule_score만)을 이긴다** = P1 가치 증명.
"""
import numpy as np

import evaluate
import features
import synth
import train


def test_to_matrix_shapes_and_group_sorted():
    rows = synth.make_synthetic(n_groups=5, per_group=4, seed=1)
    X, y, g = features.to_matrix(rows)
    assert X.shape == (20, len(features.FEATURE_COLUMNS))
    assert y.shape == (20,) and g.shape == (20,)
    assert list(g) == sorted(g)                       # 그룹 연속(LambdaMART 요건)


def test_group_sizes():
    g = np.array([0, 0, 0, 1, 1, 2])
    assert features.group_sizes(g) == [3, 2, 1]


def test_ndcg_perfect_and_reversed():
    yt = np.array([2, 1, 0]); grp = np.array([0, 0, 0])
    assert evaluate.ndcg_at_k(yt, np.array([3.0, 2.0, 1.0]), grp, k=3) == 1.0   # 완벽 정렬
    assert evaluate.ndcg_at_k(yt, np.array([1.0, 2.0, 3.0]), grp, k=3) < 1.0    # 역순


def test_relevance_and_baseline_columns():
    assert features.RELEVANCE["ADD_CART"] == 2 and features.RELEVANCE["VIEW"] == 1
    rows = synth.make_synthetic(n_groups=2, per_group=3, seed=2)
    base = features.baseline_scores(rows)
    assert base.shape == (6,)


def test_ml_beats_rule_baseline_end_to_end():
    rows = synth.make_synthetic(n_groups=400, per_group=8, seed=7)
    groups_all = sorted({r["group"] for r in rows})
    cut = int(len(groups_all) * 0.75)
    train_g, test_g = set(groups_all[:cut]), set(groups_all[cut:])
    tr = [r for r in rows if r["group"] in train_g]
    te = [r for r in rows if r["group"] in test_g]

    Xtr, ytr, gtr = features.to_matrix(tr)
    Xte, yte, gte = features.to_matrix(te)
    model = train.train(Xtr, ytr, gtr, random_state=0)

    model_score = model.predict(Xte)
    baseline_score = features.baseline_scores(te)   # rule_score만(개인화 없음)
    res = evaluate.compare(yte, model_score, baseline_score, gte, k=5)

    # ML이 규칙 baseline 이상(신호를 심었으니 실제론 상회) — P1 가치 검증
    assert res["model"]["ndcg@k"] >= res["baseline"]["ndcg@k"]
    assert res["model"]["ndcg@k"] > 0.7             # 학습이 실제로 됐는지(비자명)
