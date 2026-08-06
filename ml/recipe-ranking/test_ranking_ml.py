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
         "user_ing_affinity": 0.6, "request_ctx": {"budget_fit": 0.7}},
        {"user_id": 1, "session_id": "s", "recipe_id": 11, "relevance": 0,
         "score_stock": None, "score_expiry": None, "score_cost": None, "rule_score": None,
         "pop_view": 0, "pop_cart": 0, "user_events": 0, "user_recipe_affinity": False,
         "request_ctx": None},
    ]
    rows = features.raw_to_feature_rows(raw)
    assert rows[0]["group"] == "1:s" and rows[0]["relevance"] == 2
    assert abs(rows[0]["pop_ctr"] - 4 / 10) < 1e-9          # pop_cart/(pop_view+1)
    assert rows[0]["user_recipe_affinity"] == 1.0
    assert rows[0]["user_ing_affinity"] == 0.6
    assert rows[0]["budget_fit"] == 0.7
    assert rows[1]["score_stock"] == 0.0 and rows[1]["budget_fit"] == 0.5   # 결측→중립
    # 변환행이 학습행렬로 들어가는지(파이프라인 연결)
    X, y, g = features.to_matrix(rows)
    assert X.shape == (2, len(features.FEATURE_COLUMNS))


def test_extract_module_importable():
    import extract   # psycopg 없이도 import 가능해야(연결은 호출 시점)
    assert hasattr(extract, "activity_ready") and hasattr(extract, "extract_feature_rows")


def _trained_model():
    import synth, features, train
    rows = synth.make_synthetic(300, 8, seed=3)
    X, y, g = features.to_matrix(rows)
    return train.train(X, y, g, random_state=0)


def test_serve_cold_start_and_no_model():
    import serve
    req = serve.RankRequest(user_id=1, candidates=[
        serve.Candidate(recipe_id=10, rule_score=5.0), serve.Candidate(recipe_id=11, rule_score=3.0)])
    # 모델 없음 → personalized=false, 순서 보존
    r = serve.Ranker().rank(req)
    assert r.personalized is False and [s.recipe_id for s in r.order] == [10, 11]
    # 모델 있어도 이력<임계(콜드스타트) → false
    rk = serve.Ranker(model=_trained_model(), feature_provider=lambda u, ids: {"user_events": 0})
    assert rk.rank(req).personalized is False


def test_serve_personalizes_when_data_present():
    import serve
    model = _trained_model()
    # 이력 충분 + recipe 11에 유리한 피처(친화도·인기) → 재정렬
    def fp(user_id, ids):
        return {"user_events": 50, "per_recipe": {
            10: {"pop_ctr": 0.1, "user_recipe_affinity": 0.0, "pop_view": 5, "pop_cart": 0},
            11: {"pop_ctr": 0.9, "user_recipe_affinity": 1.0, "pop_view": 10, "pop_cart": 9}}}
    req = serve.RankRequest(user_id=7, candidates=[
        serve.Candidate(recipe_id=10, score_stock=0.5, rule_score=5.0),
        serve.Candidate(recipe_id=11, score_stock=0.5, rule_score=5.0)])
    r = serve.Ranker(model=model, feature_provider=fp).rank(req)
    assert r.personalized is True
    assert {s.recipe_id for s in r.order} == {10, 11}       # 같은 후보 집합 유지
    assert len(r.order) == 2


def test_serve_endpoint_health_and_fallback():
    import serve
    from fastapi.testclient import TestClient
    serve.set_ranker(serve.Ranker())                        # 모델 없음
    c = TestClient(serve.app)
    assert c.get("/health").json()["model_loaded"] is False
    resp = c.post("/rank/personalize", json={"user_id": 1,
                  "candidates": [{"recipe_id": 10, "rule_score": 5.0}]})
    assert resp.status_code == 200 and resp.json()["personalized"] is False


def test_no_target_leakage_affinity_bounded_by_shown_at():
    """#535 회귀 가드 — 친화도(ura/uia)가 '노출 시점(shown_at) 이전' 이벤트로만 산출되는지.
    라벨은 노출 후 30분 이벤트라, 친화도가 그와 겹치면 target leakage + train-serve skew.
    아래 불변식이 깨지면 누수 재도입 → shown_at 경계를 반드시 유지할 것."""
    sql = features.EXTRACT_SQL
    assert "i.shown_at" in sql, "ev가 shown_at을 노출해야 시간 경계에 쓸 수 있다"
    # ura: 노출 이전(<shown_at) + impression 단위 키. 옛 (user,recipe) 전역 distinct면 라벨까지 포함(누수).
    assert "e2.occurred_at < ev.shown_at" in sql, "#535: ura가 shown_at 이전으로 바운드되지 않음(누수)"
    assert "ura.impression_id = ev.impression_id" in sql, "#535: ura는 impression 단위 조인이어야"
    assert "ura.recipe_id = ev.recipe_id" not in sql, "#535: 옛 전역 ura 조인(누수)이 잔존"
    # uia(liked_by_imp): 노출 이전 ADD_CART 재료로 바운드
    assert "e.occurred_at < ev.shown_at" in sql, "#535: uia 재료친화도가 shown_at 이전으로 바운드되지 않음(누수)"
    # ua(유저 활동량): 노출 이전 + impression 단위(옛 전역 count는 라벨창 포함 → 누수)
    assert "e3.occurred_at < ev.shown_at" in sql, "#535: ua(활동량)가 shown_at 이전으로 바운드되지 않음(누수)"
    assert "ua.impression_id = ev.impression_id" in sql, "#535: ua는 impression 단위 조인이어야"


def test_affinity_window_shared_train_serve():
    """#535: 친화도 시간창을 학습(extract)·서빙(serve)이 공유해 train-serve skew 방지(드리프트 가드)."""
    import serve
    assert isinstance(features.AFFINITY_WINDOW_DAYS, int) and features.AFFINITY_WINDOW_DAYS > 0
    assert serve.AFFINITY_WINDOW_DAYS == features.AFFINITY_WINDOW_DAYS


def test_serve_uia_definition_aligned_with_training():
    """#535: 서빙 uia가 학습과 '정의' 일치 — 대화선호뿐 아니라 ADD_CART 재료(행동신호)도 포함하는지 가드.
    옛 서빙은 대화선호만 써서 학습(행동+대화)과 skew였다. (DB 없이 소스 정적 검사)"""
    import inspect
    import serve
    src = inspect.getsource(serve.pg_feature_provider)
    assert "ADD_CART" in src and "recipe_ingredient" in src, \
        "#535: 서빙 uia가 ADD_CART 재료(행동신호)를 안 씀 → 학습과 정의 불일치(skew)"
    assert "AFFINITY_WINDOW_DAYS" in src, "#535: 서빙 uia 행동신호도 학습과 동일 시간창을 써야"


def test_reload_endpoint_swaps_model_and_survives_missing(tmp_path, monkeypatch):
    import os
    import pickle
    import serve
    from fastapi.testclient import TestClient
    serve.set_ranker(serve.Ranker())                        # 모델 없음 상태로 시작
    c = TestClient(serve.app)
    # 모델 파일 없음/미설정 → reload는 비치명 실패(기존 상태 유지, 다운그레이드 없음)
    monkeypatch.delenv("RANKING_MODEL_PATH", raising=False)
    assert c.post("/reload").json()["reloaded"] is False
    assert c.get("/health").json()["model_loaded"] is False
    # 재학습이 새 모델을 저장한 상황 → reload가 떠 있는 채로 교체(재기동 불필요)
    path = tmp_path / "ranker.pkl"
    with open(path, "wb") as f:
        pickle.dump(_trained_model(), f)
    monkeypatch.setenv("RANKING_MODEL_PATH", str(path))
    body = c.post("/reload").json()
    assert body["reloaded"] is True and body["model_loaded"] is True
    assert c.get("/health").json()["model_loaded"] is True
    # 파일이 깨져도(로드 실패) 기존 모델 유지 — 서비스 다운그레이드 없음
    with open(path, "wb") as f:
        f.write(b"not a pickle")
    assert c.post("/reload").json()["reloaded"] is False
    assert c.get("/health").json()["model_loaded"] is True  # 여전히 직전 모델 보유
