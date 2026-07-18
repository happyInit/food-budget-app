"""ML 서빙 — 학습된 랭커로 후보 레시피 재랭킹 (SERVING.md §2 계약).

mealplan 규칙 랭킹(P0)이 낸 후보 + 규칙점수 3분해를 받아 개인화 점수로 재정렬한다.
콜드스타트(이력<임계)·모델 부재·피처조회 장애 → **personalized=false**(호출측 mealplan이 규칙순 유지).
자체 모델이라 호출당 0원·추론 ~1ms. 유저·인기도 피처는 feature_provider가 조회(주입 가능=테스트).
"""
from __future__ import annotations

import math
import os

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel, Field

from features import FEATURE_COLUMNS

MIN_EVENTS = int(os.environ.get("RANKING_MIN_EVENTS", "20"))   # 콜드스타트 임계


class Candidate(BaseModel):
    recipe_id: int
    score_stock: float = 0.0          # =coverage(규칙 랭커 산출)
    score_expiry: float = 0.0         # =expiring_used
    score_cost: float | None = None   # 예산적합
    rule_score: float = 0.0


class RankRequest(BaseModel):
    user_id: int
    candidates: list[Candidate] = Field(default_factory=list)


class Scored(BaseModel):
    recipe_id: int
    ml_score: float


class RankResponse(BaseModel):
    personalized: bool
    order: list[Scored]


class Ranker:
    """모델 + 피처조회 provider를 품고 재랭킹. 둘 다 주입 → 테스트는 합성 모델·fake provider."""

    def __init__(self, model=None, feature_provider=None):
        self._model = model
        self._fp = feature_provider   # (user_id, recipe_ids) -> {"user_events": int, "per_recipe": {rid: {...}}}

    def rank(self, req: RankRequest) -> RankResponse:
        cands = req.candidates
        if not cands:
            return RankResponse(personalized=False, order=[])
        if self._model is None or self._fp is None:
            return self._fallback(cands)                 # 모델/피처 미비 → 규칙순
        try:
            feats = self._fp(req.user_id, [c.recipe_id for c in cands])
        except Exception:                                # noqa: BLE001 — 피처조회 장애 → 안전 폴백
            return self._fallback(cands)
        if int(feats.get("user_events", 0)) < MIN_EVENTS:
            return self._fallback(cands)                 # 콜드스타트
        scores = self._model.predict(self._matrix(cands, feats))
        ranked = sorted(zip(cands, scores), key=lambda t: -float(t[1]))
        return RankResponse(personalized=True,
                            order=[Scored(recipe_id=c.recipe_id, ml_score=float(s)) for c, s in ranked])

    def _fallback(self, cands) -> RankResponse:
        # 규칙순(입력 순서) 보존 — 점수 0. mealplan이 personalized=false면 규칙순 그대로 씀.
        return RankResponse(personalized=False,
                            order=[Scored(recipe_id=c.recipe_id, ml_score=0.0) for c in cands])

    def _matrix(self, cands, feats) -> np.ndarray:
        per = feats.get("per_recipe", {})
        user_activity = math.log1p(float(feats.get("user_events", 0)))
        rows = []
        for c in cands:
            pr = per.get(c.recipe_id, {}) or {}
            pv, pc = float(pr.get("pop_view", 0)), float(pr.get("pop_cart", 0))
            row = {
                "score_stock": c.score_stock, "score_expiry": c.score_expiry,
                "score_cost": c.score_cost or 0.0, "rule_score": c.rule_score,
                "pop_view": pv, "pop_cart": pc, "pop_ctr": pc / (pv + 1.0),
                "user_activity": user_activity,
                "user_recipe_affinity": float(pr.get("user_recipe_affinity", 0.0)),
                "user_ing_affinity": float(pr.get("user_ing_affinity", 0.0)),
                "budget_fit": float(pr.get("budget_fit", 0.5)),
            }
            rows.append([row[col] for col in FEATURE_COLUMNS])
        return np.array(rows, dtype=float)


# ── FastAPI 앱 (SERVING.md §2 계약) ──
app = FastAPI(title="recipe-ranking serving")
_ranker = Ranker()   # 기본 = 모델 없음(항상 personalized=false). 배포 시 load_model로 주입.


def set_ranker(ranker: Ranker) -> None:
    """기동 시 모델·provider 주입(배포/테스트)."""
    global _ranker
    _ranker = ranker


@app.post("/rank/personalize", response_model=RankResponse)
def rank_personalize(req: RankRequest) -> RankResponse:
    return _ranker.rank(req)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model_loaded": _ranker._model is not None}
