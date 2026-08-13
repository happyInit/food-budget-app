"""ML 서빙 — 학습된 랭커로 후보 레시피 재랭킹 (SERVING.md §2 계약).

mealplan 규칙 랭킹(P0)이 낸 후보 + 규칙점수 3분해를 받아 개인화 점수로 재정렬한다.
콜드스타트(이력<임계)·모델 부재·피처조회 장애 → **personalized=false**(호출측 mealplan이 규칙순 유지).
자체 모델이라 호출당 0원·추론 ~1ms. 유저·인기도 피처는 feature_provider가 조회(주입 가능=테스트).
"""
from __future__ import annotations

import logging
import math
import os

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel, Field

from features import AFFINITY_WINDOW_DAYS, FEATURE_COLUMNS

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


# ── PG 피처 provider — activity에서 유저 이벤트수 + 레시피 인기도 조회(배포용) ──
def pg_feature_provider(user_id: int, recipe_ids: list[int]) -> dict:
    """activity.user_event에서 유저 활동성 + 레시피 인기도(best-effort). 실패/데이터無 → 콜드스타트({})."""
    import os

    import psycopg
    dsn = (f"host={os.environ.get('PGHOST', '192.168.0.8')} port={os.environ.get('PGPORT', '5432')} "
           f"dbname={os.environ.get('PGDATABASE', 'foodbudget')} user={os.environ.get('PGUSER', 'fbapp')} "
           f"password={os.environ.get('PGPASSWORD', '')}")
    try:
        with psycopg.connect(dsn, connect_timeout=2) as c, c.cursor() as cur:
            # #535: 친화도·활동성은 학습(features.AFFINITY_WINDOW_DAYS)과 동일 시간창으로 — train-serve 정렬.
            #   (user_event는 pruner로 보존창 정리되지만, 창이 더 길어도 여기서 명시적으로 맞춘다.)
            cur.execute("select count(*) from activity.user_event "
                        "where user_id = %s and occurred_at >= now() - (%s * interval '1 day')",
                        (user_id, AFFINITY_WINDOW_DAYS))
            n = cur.fetchone()[0]
            cur.execute("""select recipe_id,
                             count(*) filter (where event_type='VIEW')     as pv,
                             count(*) filter (where event_type='ADD_CART')  as pc,
                             bool_or(user_id = %s)                          as mine
                           from activity.user_event
                           where recipe_id = any(%s)
                             and occurred_at >= now() - (%s * interval '1 day')
                           group by recipe_id""", (user_id, recipe_ids, AFFINITY_WINDOW_DAYS))
            per = {r[0]: {"pop_view": r[1], "pop_cart": r[2],
                          "user_recipe_affinity": 1.0 if r[3] else 0.0} for r in cur.fetchall()}
            # 인기도 = user_event(보존창) + activity.recipe_popularity(보존기간 지나 삭제된 분의 누적,
            #   §4.1·PR #194). 둘을 합산해야 정확 — 테이블만=최근 유실, 원문만=오래된 것 유실.
            #   미적용(테이블 부재)이면 to_regclass가 NULL → 건너뜀 → user_event만(무해).
            cur.execute("select to_regclass('activity.recipe_popularity')")
            if cur.fetchone()[0] is not None:
                cur.execute("""select recipe_id, view_cnt, add_cart_cnt
                               from activity.recipe_popularity where recipe_id = any(%s)""", (recipe_ids,))
                for rid, vc, ac in cur.fetchall():
                    d = per.setdefault(rid, {"pop_view": 0, "pop_cart": 0, "user_recipe_affinity": 0.0})
                    d["pop_view"] = int(d["pop_view"]) + int(vc or 0)
                    d["pop_cart"] = int(d["pop_cart"]) + int(ac or 0)
            # user_ing_affinity = 후보 레시피 재료 ∩ 유저 선호 재료 비율.
            # #535: 학습(features.uia=liked_by_imp)과 '정의'를 일치시킨다 —
            #   선호 재료 = ① 노출 이전(=지금 이전, 창=AFFINITY_WINDOW_DAYS) ADD_CART 레시피 재료(행동신호)
            #             ∪ ② 대화 선호(user_chat_pref, 있으면). 옛 서빙은 ②만 써서 학습과 skew였다.
            liked: set[int] = set()
            cur.execute("""select distinct ri.item_id
                             from activity.user_event e
                             join public.recipe_ingredient ri
                               on ri.recipe_id = e.recipe_id and ri.item_id is not null
                            where e.user_id = %s and e.event_type = 'ADD_CART'
                              and e.occurred_at >= now() - (%s * interval '1 day')""",
                        (user_id, AFFINITY_WINDOW_DAYS))
            liked.update(r[0] for r in cur.fetchall())
            cur.execute("select to_regclass('activity.user_chat_pref')")   # 대화 선호(옵션·스냅샷)
            if cur.fetchone()[0] is not None:
                cur.execute("select liked_item_ids from activity.user_chat_pref where user_id = %s", (user_id,))
                row = cur.fetchone()
                if row and row[0]:
                    liked.update(row[0])
            if liked:
                cur.execute("""select recipe_id, array_agg(item_id) from public.recipe_ingredient
                               where recipe_id = any(%s) and item_id is not null group by recipe_id""", (recipe_ids,))
                for rid, items in cur.fetchall():
                    items = [i for i in items if i is not None]
                    if items:
                        aff = len(liked.intersection(items)) / len(items)
                        per.setdefault(rid, {"pop_view": 0, "pop_cart": 0, "user_recipe_affinity": 0.0})["user_ing_affinity"] = aff
        return {"user_events": n, "per_recipe": per}
    except Exception:   # noqa: BLE001 — 테이블 부재/장애 → 콜드스타트(규칙순)
        return {"user_events": 0}


# ── FastAPI 앱 (SERVING.md §2 계약) ──
_log = logging.getLogger("ranking-serving")

app = FastAPI(title="recipe-ranking serving")
_ranker = Ranker()   # 기본 = 모델 없음(항상 personalized=false).


def set_ranker(ranker: Ranker) -> None:
    """기동 시 모델·provider 주입(배포/테스트)."""
    global _ranker
    _ranker = ranker


# 🔴 모델 적재 상태 — `/health` 가 그대로 노출한다 (체크리스트 `1-21`).
#   종전에는 파일 부재·pickle 실패를 **로그 한 줄 없이** 삼키고 `model=None` 으로 떠서,
#   "규칙순으로 폴백 중"인지 "ML 이 도는 중"인지 **밖에서 구분할 방법이 없었다**.
#   `/health` 는 어느 쪽이든 `status: ok` 를 반환해 readiness·liveness 를 통과한다(= 의도된 설계 —
#   모델이 없어도 규칙순 서빙은 해야 한다). 그래서 **실패는 조용히 사라지고 아무도 모른다.**
#   ⇒ 여기서 하는 일 = ① 왜 없는지 **로그로 남긴다** ② `/health` 에 **이유를 실어** 즉시 진단 가능하게.
_model_status: dict = {"model_loaded": False, "model_source": "not_initialized"}


def _init_from_env() -> None:
    """RANKING_MODEL_PATH 있으면 모델 로드 + PG provider 배선. 없으면 폴백(규칙순).

    🔴 로드 실패는 **치명적이 아니다**(규칙순으로 계속 서빙한다). 다만 **조용해서는 안 된다** —
       그게 `1-21` 이 지적한 결함이고, C-20(모델을 이미지에 굽기)으로 가면
       *"이미지 배선이 틀려도 드러나지 않는"* 경로가 되므로 특히 중요하다.
    """
    import os
    import pickle

    model, status = None, {"model_loaded": False, "model_path": None,
                           "model_source": None, "model_error": None}
    path = os.environ.get("RANKING_MODEL_PATH")
    status["model_path"] = path

    if not path:
        status["model_source"] = "env_unset"
        _log.warning("RANKING_MODEL_PATH 미설정 — 규칙순 폴백으로 기동한다(ML 재랭킹 없음)")
    elif not os.path.exists(path):
        status["model_source"] = "file_missing"
        _log.warning("모델 파일이 없다 (%s) — 규칙순 폴백으로 기동한다. "
                     "재학습이 아직 안 돌았거나 볼륨/이미지 배선이 틀렸을 수 있다", path)
    else:
        try:
            with open(path, "rb") as f:
                model = pickle.load(f)
        except Exception as exc:   # noqa: BLE001 — 로드 실패 → 모델 없이(폴백)
            status["model_source"] = "load_failed"
            status["model_error"] = type(exc).__name__
            _log.exception("모델 로드 실패 (%s) — 규칙순 폴백으로 기동한다", path)
        else:
            status.update(model_loaded=True, model_source="file",
                          model_class=type(model).__name__,
                          model_mtime=int(os.path.getmtime(path)),
                          model_bytes=os.path.getsize(path))
            _log.info("모델 적재 완료 — %s (%s, %d bytes)",
                      path, type(model).__name__, os.path.getsize(path))

    _model_status.clear()
    _model_status.update(status)
    set_ranker(Ranker(model=model, feature_provider=pg_feature_provider))


_init_from_env()


@app.post("/rank/personalize", response_model=RankResponse)
def rank_personalize(req: RankRequest) -> RankResponse:
    return _ranker.rank(req)


@app.post("/reload")
def reload_model() -> dict:
    """재학습 배치가 새 모델 저장 후 호출 → 떠 있는 채로 모델만 교체(프로세스 재기동 불필요).
    푸시 트리거(폴링 아님)·결과 반환(조용한 실패 없음). 로드 실패 시 기존 모델 유지(다운그레이드 없음).
    swap은 set_ranker의 전역 1회 대입(GIL 하 원자적) — 처리 중 요청과 경합 안 함."""
    import os
    import pickle
    path = os.environ.get("RANKING_MODEL_PATH")
    if not path or not os.path.exists(path):
        return {"reloaded": False, "reason": "no_model_file"}
    try:
        with open(path, "rb") as f:
            model = pickle.load(f)
    except Exception as exc:   # noqa: BLE001 — 로드 실패 → 기존 모델 유지(무손상)
        # 🔴 재학습이 새 모델을 저장했는데 그게 깨졌다면 **가장 알아야 할 순간**이다.
        #    반환값만으로는 호출자(retrain 배치)의 stdout 에만 남고 서빙 로그엔 흔적이 없었다.
        _log.exception("모델 재적재 실패 (%s) — 기존 모델을 유지한다", path)
        return {"reloaded": False, "error": type(exc).__name__}
    set_ranker(Ranker(model=model, feature_provider=pg_feature_provider))
    _model_status.update(model_loaded=True, model_source="reload", model_path=path,
                         model_error=None, model_class=type(model).__name__,
                         model_mtime=int(os.path.getmtime(path)),
                         model_bytes=os.path.getsize(path))
    _log.info("모델 재적재 완료 — %s (%s, %d bytes)", path, type(model).__name__,
              os.path.getsize(path))
    return {"reloaded": True, "model_loaded": True}


@app.get("/health")
def health() -> dict:
    """🔴 `status` 는 모델 유무와 무관하게 `ok` 다 — 모델이 없어도 규칙순 서빙은 정상이고,
    여기서 실패를 반환하면 readiness 가 떨어져 **폴백조차 못 하게** 된다(의도된 설계).

    대신 **왜 모델이 없는지를 실어 보낸다**(`1-21`) — 종전에는 `model_loaded` 불리언 하나뿐이라
    *"파일이 없나 · 경로가 안 잡혔나 · pickle 이 깨졌나"* 를 밖에서 구분할 수 없었다.
    """
    loaded = _ranker._model is not None
    return {"status": "ok", "model_loaded": loaded, **_model_status, "model_loaded_effective": loaded}
