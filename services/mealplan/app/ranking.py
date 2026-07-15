"""순수 레시피 랭킹(#32) — DB·전역·시계 무관. tests/test_ranking.py 로 철저히 단위테스트.

점수 = 보유재료 커버리지↑ + 임박재료 사용↑ − 예산초과 페널티.
입력: pantry 재고(보유/임박 item_id 집합) + 후보 레시피(재료 item_id + 최저가 합 추정) + 예산.
핸들러(routers.py)는 pantry seam + public 레시피 조회 결과를 이 함수에 넣기만 한다(로직 없음).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# 가중치 — 커버리지가 지배적, 임박 사용은 보너스, 예산초과는 비율 페널티.
COVERAGE_W = 10.0
EXPIRING_W = 3.0
BUDGET_PENALTY_W = 5.0


@dataclass(frozen=True)
class Candidate:
    """후보 레시피 1건 — 이미 재료가 표준 품목(item_id)으로 매핑된 상태."""
    id: int
    name: str
    ingredient_item_ids: tuple[int, ...]
    est_cost: int | None = None          # 재료 최저가 합(원). 미상이면 None → 예산 페널티 제외.


@dataclass(frozen=True)
class Ranked:
    id: int
    name: str
    score: float
    coverage: float
    matched_item_ids: tuple[int, ...]
    expiring_used: int
    est_cost: int | None


def _score(c: Candidate, owned: set[int], expiring: set[int],
           budget: int | None) -> tuple[float, float, tuple[int, ...], int]:
    total = len(c.ingredient_item_ids)
    if total == 0:
        return 0.0, 0.0, (), 0
    matched = tuple(i for i in c.ingredient_item_ids if i in owned)
    coverage = len(matched) / total
    expiring_used = sum(1 for i in c.ingredient_item_ids if i in expiring)
    score = COVERAGE_W * coverage + EXPIRING_W * expiring_used
    # 예산초과 페널티(예산·추정가가 둘 다 있고 초과할 때만).
    if budget is not None and budget > 0 and c.est_cost is not None and c.est_cost > budget:
        over_ratio = (c.est_cost - budget) / budget
        score -= BUDGET_PENALTY_W * over_ratio
    return round(score, 6), round(coverage, 6), matched, expiring_used


def rank_recipes(candidates: Iterable[Candidate], owned_item_ids: Iterable[int],
                 expiring_item_ids: Iterable[int] = (), budget: int | None = None) -> list[Ranked]:
    """점수순 정렬(내림차순). 동점=커버리지↓, 다시 동점=id↑ 안정적 결정."""
    owned = set(owned_item_ids)
    expiring = set(expiring_item_ids)
    ranked = [
        Ranked(c.id, c.name, *_score(c, owned, expiring, budget), c.est_cost)
        for c in candidates
    ]
    ranked.sort(key=lambda r: (-r.score, -r.coverage, r.id))
    return ranked


def group_recipe_rows(rows: Iterable[dict]) -> list[Candidate]:
    """public 조인 flat rows(recipe_id, recipe_name, item_id, ing_cost) → [Candidate].

    item_id=None(미매칭 재료)은 커버리지 계산서 제외되나, 있는 최저가는 est_cost 합에 반영.
    est_cost 는 재료 최저가가 하나라도 있을 때만 정수 합, 전부 None이면 None.
    """
    order: list[int] = []
    by_id: dict[int, dict] = {}
    for r in rows:
        rid = r["recipe_id"]
        g = by_id.get(rid)
        if g is None:
            g = {"name": r["recipe_name"], "items": [], "cost": 0, "has_cost": False}
            by_id[rid] = g
            order.append(rid)
        if r["item_id"] is not None:
            g["items"].append(r["item_id"])
        if r.get("ing_cost") is not None:
            g["cost"] += int(r["ing_cost"])
            g["has_cost"] = True
    return [
        Candidate(rid, by_id[rid]["name"], tuple(by_id[rid]["items"]),
                  by_id[rid]["cost"] if by_id[rid]["has_cost"] else None)
        for rid in order
    ]
