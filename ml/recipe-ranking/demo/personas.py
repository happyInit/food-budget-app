"""발표용 데모 데이터 — 페르소나 기반 합성 클릭스트림.

synth.py(무작위 신호)와 달리 **해석 가능한** 신호를 심는다: 각 유저는 뚜렷한 취향
(예: 매운 돼지고기 애호)을 갖고, 그 취향에 맞는 레시피를 규칙점수와 무관하게 클릭/담기한다.
→ "규칙점수만 쓰는 baseline"이 못 잡는 취향을 "user_ing_affinity 등 개인화 피처를 쓰는 ML"이
   잡아 재정렬하는 것을 **실 레시피명으로** 보여준다(Layer 2). 전부 격리·합성(프로덕션 무접촉).

⚠️ 데모 전용. 실 운영은 activity 클릭스트림 축적 → extract.py. 여기 수치는 시연 신호이지 실측 아님.
"""
from __future__ import annotations

import numpy as np

from features import FEATURE_COLUMNS

# ── 합성 레시피 카탈로그 (실 레시피명 — 시연 설득력) ──
#   protein: 단백질군 · spicy: 매움(0/1) · cost: 1저렴 2보통 3비쌈
RECIPES: list[dict] = [
    {"id": 101, "name": "돼지고기 김치찌개", "protein": "pork", "spicy": 1, "cost": 2},
    {"id": 102, "name": "매콤 제육볶음", "protein": "pork", "spicy": 1, "cost": 2},
    {"id": 103, "name": "고추장 삼겹살 두루치기", "protein": "pork", "spicy": 1, "cost": 3},
    {"id": 104, "name": "수육 보쌈", "protein": "pork", "spicy": 0, "cost": 3},
    {"id": 105, "name": "닭가슴살 샐러드", "protein": "chicken", "spicy": 0, "cost": 1},
    {"id": 106, "name": "닭가슴살 스테이크", "protein": "chicken", "spicy": 0, "cost": 2},
    {"id": 107, "name": "매운 닭볶음탕", "protein": "chicken", "spicy": 1, "cost": 2},
    {"id": 108, "name": "닭가슴살 계란볶음밥", "protein": "chicken", "spicy": 0, "cost": 1},
    {"id": 109, "name": "두부조림", "protein": "tofu", "spicy": 0, "cost": 1},
    {"id": 110, "name": "순두부찌개", "protein": "tofu", "spicy": 1, "cost": 1},
    {"id": 111, "name": "두부 김치", "protein": "tofu", "spicy": 1, "cost": 1},
    {"id": 112, "name": "콩나물국", "protein": "veg", "spicy": 0, "cost": 1},
    {"id": 113, "name": "된장찌개", "protein": "veg", "spicy": 0, "cost": 1},
    {"id": 114, "name": "소불고기", "protein": "beef", "spicy": 0, "cost": 3},
    {"id": 115, "name": "소고기 미역국", "protein": "beef", "spicy": 0, "cost": 3},
    {"id": 116, "name": "차돌된장찌개", "protein": "beef", "spicy": 0, "cost": 3},
    {"id": 117, "name": "고등어구이", "protein": "seafood", "spicy": 0, "cost": 2},
    {"id": 118, "name": "매운 오징어볶음", "protein": "seafood", "spicy": 1, "cost": 2},
    {"id": 119, "name": "새우볶음밥", "protein": "seafood", "spicy": 0, "cost": 2},
    {"id": 120, "name": "계란말이", "protein": "veg", "spicy": 0, "cost": 1},
]
RECIPE_BY_ID = {r["id"]: r for r in RECIPES}

# ── 페르소나 — 취향을 affinity(0~1)로 정의. 이 취향이 라벨(클릭/담기)을 만든다. ──
PERSONAS: dict[str, dict] = {
    "spicy_pork": {
        "label": "매운 돼지고기 애호가",
        "desc": "매운맛 + 돼지고기를 선호. 가격엔 둔감.",
        "affinity": lambda r: 1.0 if (r["protein"] == "pork" and r["spicy"]) else (0.55 if r["protein"] == "pork" or r["spicy"] else 0.15),
    },
    "budget": {
        "label": "저예산 지향",
        "desc": "무조건 싼 레시피(cost=1) 선호. 재료군은 무관.",
        "affinity": lambda r: 1.0 if r["cost"] == 1 else (0.4 if r["cost"] == 2 else 0.1),
    },
    "chicken_diet": {
        "label": "닭가슴살 다이어터",
        "desc": "닭가슴살(chicken) + 저렴/담백 선호. 매운·기름진 것 회피.",
        "affinity": lambda r: 1.0 if (r["protein"] == "chicken" and not r["spicy"]) else (0.5 if r["protein"] == "chicken" else 0.15),
    },
}

# 데모(Layer 2)에서 before/after를 보여줄 페르소나 순서
DEMO_PERSONAS = ["spicy_pork", "budget", "chicken_diet"]


def _global_pop(rng) -> dict[int, float]:
    """레시피별 전역 인기도(0~1) — 유저 취향과 무관한 별도 신호(pop_*)."""
    return {r["id"]: float(rng.random()) for r in RECIPES}


def _impression_rows(rng, user_id: int, persona: str, group: int, pop: dict[int, float],
                     n_cand: int, user_activity: float) -> list[dict]:
    """한 노출요청(그룹) — 후보 레시피 n_cand개의 피처행 + 페르소나 유래 라벨."""
    aff_fn = PERSONAS[persona]["affinity"]
    cand = rng.choice(RECIPES, size=n_cand, replace=False)
    rows = []
    utils = []
    for r in cand:
        stock = float(rng.random()); expiry = float(rng.random()); cost = float(rng.random())
        budget_fit = {1: 0.9, 2: 0.5, 3: 0.2}[r["cost"]] + float(rng.normal(0, 0.05))
        # 규칙 종합(mealplan 모사) — 취향을 '모른다'(재고·임박·저비용만)
        rule = 0.6 * stock + 0.25 * expiry + 0.15 * budget_fit
        pv = pop[r["id"]]; pc = pv * float(rng.uniform(0.2, 0.6))
        ing_aff = float(np.clip(aff_fn(r) + rng.normal(0, 0.08), 0, 1))   # 취향 신호(핵심)
        recipe_aff = 1.0 if rng.random() < aff_fn(r) * 0.4 else 0.0        # 과거 참여(취향 비례)
        row = {
            "group": group, "_user": user_id, "_recipe_id": int(r["id"]),
            "score_stock": stock, "score_expiry": expiry, "score_cost": cost,
            "rule_score": rule, "pop_view": pv, "pop_cart": pc,
            "pop_ctr": pc / (pv + 1.0), "user_activity": user_activity,
            "user_recipe_affinity": recipe_aff, "user_ing_affinity": ing_aff,
            "budget_fit": float(np.clip(budget_fit, 0, 1)),
        }
        # 잠재 효용 = 취향(0.55) + 규칙(0.25) + 인기(0.2) → 규칙만으론 취향을 못 잡음
        utils.append(0.55 * ing_aff + 0.25 * rule + 0.2 * row["pop_ctr"] + float(rng.normal(0, 0.04)))
        rows.append(row)
    order = np.argsort(-np.array(utils))
    for r in rows:
        r["relevance"] = 0
    rows[order[0]]["relevance"] = 2                 # 최상 = 담기(ADD_CART)
    for i in order[1:3]:
        rows[i]["relevance"] = 1                     # 다음 둘 = 조회(VIEW)
    return rows


def make_training_rows(n_users: int = 120, sessions_per_user: int = 4,
                       n_cand: int = 8, seed: int = 7) -> list[dict]:
    """페르소나 유저 n_users명 × 세션 → 라벨된 피처행(to_matrix 호환)."""
    rng = np.random.default_rng(seed)
    pop = _global_pop(rng)
    personas = list(PERSONAS)
    rows: list[dict] = []
    group = 0
    for u in range(n_users):
        persona = personas[u % len(personas)]
        activity = float(np.log1p(rng.integers(20, 200)))   # 데이터有 유저(콜드스타트 아님)
        for _ in range(sessions_per_user):
            rows.extend(_impression_rows(rng, u, persona, group, pop, n_cand, activity))
            group += 1
    assert set(FEATURE_COLUMNS).issubset(rows[0]), "행이 FEATURE_COLUMNS를 포함해야 함"
    return rows, pop


def demo_candidates(persona: str, pop: dict[int, float], n: int = 8, seed: int = 42) -> list[dict]:
    """Layer 2 시연용 고정 후보셋 — 규칙점수는 취향과 무관(일부러 평평)하게,
    user_ing_affinity만 취향을 반영 → ML이 취향 레시피를 위로 올리는 걸 보여준다."""
    rng = np.random.default_rng(seed + hash(persona) % 1000)
    aff_fn = PERSONAS[persona]["affinity"]
    cand = rng.choice(RECIPES, size=n, replace=False)
    rows = []
    for r in cand:
        # 규칙점수는 취향과 무관하게 비슷하게(0.4~0.6) → rule 정렬은 '일반적'
        rule = float(rng.uniform(0.4, 0.6))
        pv = pop[r["id"]]; pc = pv * 0.35
        ing_aff = float(np.clip(aff_fn(r), 0, 1))
        rows.append({
            "_recipe_id": int(r["id"]), "_name": r["name"], "_tags": _tags(r),
            "score_stock": rule, "score_expiry": 0.3, "score_cost": 0.5,
            "rule_score": rule, "pop_view": pv, "pop_cart": pc, "pop_ctr": pc / (pv + 1.0),
            "user_activity": float(np.log1p(80)),
            "user_recipe_affinity": 1.0 if ing_aff > 0.8 else 0.0,
            "user_ing_affinity": ing_aff, "budget_fit": {1: 0.9, 2: 0.5, 3: 0.2}[r["cost"]],
        })
    return rows


def _tags(r: dict) -> str:
    prot = {"pork": "돼지", "chicken": "닭", "tofu": "두부", "beef": "소", "seafood": "해산물", "veg": "채소"}[r["protein"]]
    return f"{prot}{'·매움' if r['spicy'] else ''}·{['', '저렴', '보통', '비쌈'][r['cost']]}"
