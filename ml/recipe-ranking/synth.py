"""합성 클릭스트림 — 실 데이터(동의·축적) 대기 중 파이프라인을 end-to-end 검증하기 위한 것.

'신호를 심는다': 유저의 실제 클릭(관련도)은 규칙점수뿐 아니라 **유저-레시피 친화도·인기도**에도
의존하도록 생성한다. 그래야 "규칙점수만 쓰는 baseline"을 "모든 피처를 쓰는 ML"이 이기는 게
검증되고, 그게 곧 P1(개인화)의 가치 증명이다. numpy만 사용.
"""
from __future__ import annotations

import numpy as np

from features import FEATURE_COLUMNS


def make_synthetic(n_groups: int = 300, per_group: int = 8, seed: int = 0) -> list[dict]:
    """유저 세션 n_groups개, 각 세션 per_group개 레시피 노출 → 라벨된 row dict 리스트.

    group = 노출요청 id(유저·세션). relevance = 세션 내 잠재효용 순위로 부여(0/1/2).
    """
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    for g in range(n_groups):
        # 규칙점수 3종 + 맥락
        stock = rng.random(per_group)
        expiry = rng.random(per_group)
        cost = rng.random(per_group)
        budget_fit = rng.random(per_group)
        # 규칙 종합점수(mealplan 가중 모사) — 효용의 '일부'만 설명
        rule = 0.6 * stock + 0.25 * expiry + 0.15 * budget_fit
        # 인기도·유저이력 — 규칙엔 없는 개인화 신호
        pop_view = rng.random(per_group)
        pop_cart = rng.random(per_group)
        pop_ctr = rng.random(per_group)
        user_activity = np.full(per_group, rng.random())        # 유저 단위(세션 내 상수)
        user_recipe_affinity = (rng.random(per_group) < 0.3).astype(float)
        user_ing_affinity = rng.random(per_group)
        # 잠재 효용 = 규칙 0.4 + 개인화 0.6(친화도·인기도) + 노이즈 → 규칙만으론 부족
        utility = (0.4 * rule + 0.3 * user_recipe_affinity + 0.2 * pop_ctr
                   + 0.1 * user_ing_affinity + rng.normal(0, 0.05, per_group))
        order = np.argsort(-utility)                             # 효용 높은 순
        relevance = np.zeros(per_group, dtype=int)
        relevance[order[0]] = 2                                  # 최상 = 담기(ADD_CART)
        relevance[order[1:3]] = 1                                # 다음 둘 = 조회(VIEW)
        for i in range(per_group):
            rows.append({
                "group": g,
                "relevance": int(relevance[i]),
                "score_stock": stock[i], "score_expiry": expiry[i], "score_cost": cost[i],
                "rule_score": rule[i], "pop_view": pop_view[i], "pop_cart": pop_cart[i],
                "pop_ctr": pop_ctr[i], "user_activity": user_activity[i],
                "user_recipe_affinity": user_recipe_affinity[i],
                "user_ing_affinity": user_ing_affinity[i], "budget_fit": budget_fit[i],
            })
    assert set(FEATURE_COLUMNS).issubset(rows[0]), "합성행이 FEATURE_COLUMNS를 모두 포함해야 함"
    return rows
