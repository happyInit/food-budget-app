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


def test_raw_to_feature_rows_transform():
    # EXTRACT_SQL 원시행 형태 → 피처행 변환(파생피처·결측 처리) 검증
    raw = [
        {"user_id": 1, "session_id": "s", "recipe_id": 10, "relevance": 2,
         "score_stock": 0.8, "score_expiry": 2.0, "score_cost": 0.9, "rule_score": 8.6,
         "pop_view": 9, "pop_cart": 4, "user_events": 20, "user_recipe_affinity": True,
         "request_ctx": {"budget_fit": 0.7}},
        {"user_id": 1, "session_id": "s", "recipe_id": 11, "relevance": 0,
         "score_stock": None, "score_expiry": None, "score_cost": None, "rule_score": None,
         "pop_view": 0, "pop_cart": 0, "user_events": 0, "user_recipe_affinity": False,
         "request_ctx": None},
    ]
    rows = features.raw_to_feature_rows(raw)
    assert rows[0]["group"] == "1:s" and rows[0]["relevance"] == 2
    assert abs(rows[0]["pop_ctr"] - 4 / 10) < 1e-9          # pop_cart/(pop_view+1)
    assert rows[0]["user_recipe_affinity"] == 1.0
    assert rows[0]["budget_fit"] == 0.7
    assert rows[1]["score_stock"] == 0.0 and rows[1]["budget_fit"] == 0.5   # 결측→중립
    # 변환행이 학습행렬로 들어가는지(파이프라인 연결)
    X, y, g = features.to_matrix(rows)
    assert X.shape == (2, len(features.FEATURE_COLUMNS))


def test_extract_module_importable():
    import extract   # psycopg 없이도 import 가능해야(연결은 호출 시점)
    assert hasattr(extract, "activity_ready") and hasattr(extract, "extract_feature_rows")
