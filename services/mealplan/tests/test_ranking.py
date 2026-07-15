"""순수 랭킹(#32) 단위테스트 — DB·서버 없이 점수식·정렬·그룹핑을 철저히 검증.
이게 추천의 '딥 모듈': 핸들러는 이 함수에 재고/후보를 넣기만 하므로 여기서 로직을 다 잡는다."""
from __future__ import annotations

from app.ranking import (
    BUDGET_PENALTY_W, COVERAGE_W, EXPIRING_W, Candidate,
    group_recipe_rows, rank_recipes,
)


# ── 커버리지 ────────────────────────────────────────────────────────────────
def test_full_coverage_beats_partial():
    a = Candidate(1, "full", (10, 20))          # 2/2 보유
    b = Candidate(2, "partial", (10, 99))        # 1/2 보유
    ranked = rank_recipes([b, a], owned_item_ids=[10, 20])
    assert [r.id for r in ranked] == [1, 2]      # full 이 먼저
    assert ranked[0].coverage == 1.0
    assert ranked[1].coverage == 0.5
    assert ranked[0].matched_item_ids == (10, 20)


def test_coverage_score_value():
    c = Candidate(1, "x", (10, 20, 30, 40))      # 1/4 보유
    r = rank_recipes([c], owned_item_ids=[10])[0]
    assert r.coverage == 0.25
    assert r.score == round(COVERAGE_W * 0.25, 6)


def test_empty_ingredients_scores_zero():
    r = rank_recipes([Candidate(1, "empty", ())], owned_item_ids=[1, 2])[0]
    assert r.score == 0.0
    assert r.coverage == 0.0


def test_no_pantry_all_zero_but_stable_order():
    cs = [Candidate(3, "c", (1,)), Candidate(1, "a", (2,)), Candidate(2, "b", (3,))]
    ranked = rank_recipes(cs, owned_item_ids=[])
    assert all(r.score == 0.0 for r in ranked)
    assert [r.id for r in ranked] == [1, 2, 3]   # 동점 → id 오름차순(결정적)


# ── 임박 재료 보너스 ────────────────────────────────────────────────────────
def test_expiring_bonus_breaks_tie():
    # 둘 다 커버리지 1/2 지만 a는 임박재료(10)를 씀 → 보너스로 우선.
    a = Candidate(1, "uses_expiring", (10, 99))
    b = Candidate(2, "no_expiring", (20, 99))
    ranked = rank_recipes([b, a], owned_item_ids=[10, 20], expiring_item_ids=[10])
    assert ranked[0].id == 1
    assert ranked[0].expiring_used == 1
    assert ranked[1].expiring_used == 0


def test_expiring_score_added_per_ingredient():
    c = Candidate(1, "x", (10, 20))              # 둘 다 보유+임박
    r = rank_recipes([c], owned_item_ids=[10, 20], expiring_item_ids=[10, 20])[0]
    assert r.expiring_used == 2
    assert r.score == round(COVERAGE_W * 1.0 + EXPIRING_W * 2, 6)


# ── 예산 초과 페널티 ────────────────────────────────────────────────────────
def test_budget_over_penalizes():
    cheap = Candidate(1, "cheap", (10,), est_cost=5000)
    pricey = Candidate(2, "pricey", (10,), est_cost=20000)   # 예산 2배 초과
    ranked = rank_recipes([pricey, cheap], owned_item_ids=[10], budget=10000)
    assert ranked[0].id == 1                      # 예산 내가 위
    # pricey: over_ratio = (20000-10000)/10000 = 1.0 → score = 10 - 5*1.0 = 5
    pricey_r = next(r for r in ranked if r.id == 2)
    assert pricey_r.score == round(COVERAGE_W * 1.0 - BUDGET_PENALTY_W * 1.0, 6)


def test_no_penalty_when_within_budget():
    c = Candidate(1, "x", (10,), est_cost=8000)
    r = rank_recipes([c], owned_item_ids=[10], budget=10000)[0]
    assert r.score == round(COVERAGE_W * 1.0, 6)  # 초과 아니면 페널티 없음


def test_no_penalty_when_cost_unknown():
    c = Candidate(1, "x", (10,), est_cost=None)
    r = rank_recipes([c], owned_item_ids=[10], budget=1)[0]
    assert r.score == round(COVERAGE_W * 1.0, 6)  # est_cost None → 페널티 제외


def test_no_penalty_when_no_budget():
    c = Candidate(1, "x", (10,), est_cost=999999)
    r = rank_recipes([c], owned_item_ids=[10], budget=None)[0]
    assert r.score == round(COVERAGE_W * 1.0, 6)


# ── group_recipe_rows (DB flat rows → Candidate) ───────────────────────────
def test_group_rows_builds_candidates_and_cost():
    rows = [
        {"recipe_id": 7, "recipe_name": "김치찌개", "item_id": 10, "ing_cost": 300},
        {"recipe_id": 7, "recipe_name": "김치찌개", "item_id": 20, "ing_cost": 150},
        {"recipe_id": 9, "recipe_name": "계란말이", "item_id": 30, "ing_cost": None},
    ]
    cands = group_recipe_rows(rows)
    assert [c.id for c in cands] == [7, 9]        # 등장 순서 보존
    k = cands[0]
    assert k.ingredient_item_ids == (10, 20)
    assert k.est_cost == 450                       # 300 + 150
    assert cands[1].est_cost is None               # 재료가격 전부 None → None


def test_group_rows_skips_null_item_id_from_coverage_but_keeps_cost():
    rows = [
        {"recipe_id": 1, "recipe_name": "r", "item_id": None, "ing_cost": 500},
        {"recipe_id": 1, "recipe_name": "r", "item_id": 42, "ing_cost": 100},
    ]
    c = group_recipe_rows(rows)[0]
    assert c.ingredient_item_ids == (42,)          # None 은 커버리지 축서 제외
    assert c.est_cost == 600                        # 가격은 합산(500 + 100)
