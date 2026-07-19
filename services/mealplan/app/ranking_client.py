"""ML 재랭킹 호출 — mealplan → ranking-serving (`/rank/personalize`, SERVING.md §2).

규칙 랭킹(P0) 결과 + 규칙점수 3분해를 서빙에 넘겨 **개인화 점수로 재정렬**한다(2단계 블렌딩).
서빙 미가용/콜드스타트(`personalized=false`)/타임아웃 → **None**(호출측이 규칙순 유지). httpx.
"""
from __future__ import annotations

import httpx


def _budget_fit(est_cost, budget) -> float | None:
    return min(1.0, budget / est_cost) if (budget and est_cost) else None


async def personalize(settings, user_id: int, ranked, budget) -> list[int] | None:
    """서빙 호출 → 개인화 recipe_id 순서. flag OFF·미가용·비개인화면 None(규칙순 유지)."""
    if not settings.ranking_ml_enabled or not ranked:
        return None
    candidates = [
        {"recipe_id": r.id, "score_stock": r.coverage, "score_expiry": float(r.expiring_used),
         "score_cost": _budget_fit(r.est_cost, budget), "rule_score": r.score}
        for r in ranked
    ]
    try:
        async with httpx.AsyncClient(timeout=settings.ranking_serving_timeout_s) as client:
            resp = await client.post(
                f"{settings.ranking_serving_url}/rank/personalize",
                json={"user_id": user_id, "candidates": candidates})
            data = resp.json()
    except Exception:   # noqa: BLE001 — 서빙 미가용/타임아웃/오류 무엇이든 규칙순 폴백
        return None
    if not data.get("personalized"):
        return None
    return [o["recipe_id"] for o in data.get("order", [])]


def reorder(ranked, order: list[int]):
    """서빙 order(recipe_id 리스트)대로 ranked 재정렬. order에 없는 항목은 뒤에 원순서 보존."""
    pos = {rid: i for i, rid in enumerate(order)}
    return sorted(ranked, key=lambda r: pos.get(r.id, len(order)))
