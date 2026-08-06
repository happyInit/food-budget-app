"""피처 명세 + 추출 — 개인화 레시피 랭킹(ai-spec §3, P1).

`activity.recipe_impression`(노출+규칙점수) ⋈ `activity.user_event`(VIEW·ADD_CART=라벨)를
`(user_id, session_id, recipe_id)`로 조인해 라벨된 학습행을 만든다. 규칙점수 3종은
mealplan 랭커(P0)가 impression에 이미 로깅한 값을 재사용 — ML은 그 위에 유저행동·인기도를 얹는다.

여기서는 numpy만 쓴다(pandas 불필요). 실 PG 추출은 EXTRACT_SQL을 features.py --extract로 실행.
"""
from __future__ import annotations

import numpy as np

# 학습에 쓰는 피처 컬럼(순서 = 행렬 열 순서). README 피처 명세와 1:1.
FEATURE_COLUMNS: list[str] = [
    "score_stock", "score_expiry", "score_cost", "rule_score",   # 규칙점수(impression 로깅)
    "pop_view", "pop_cart", "pop_ctr",                            # 레시피 인기도(전역 집계)
    "user_activity", "user_recipe_affinity", "user_ing_affinity", # 유저 이력
    "budget_fit",                                                 # 맥락
]

# baseline = 규칙 종합점수만(개인화 없음). ML이 이걸 이겨야 P1 가치가 증명된다.
BASELINE_COLUMN = "rule_score"

# event_type → 관련도 라벨. ADD_CART가 주 라벨(강한 관심).
RELEVANCE = {None: 0, "VIEW": 1, "ADD_CART": 2}

# #535: 친화도(ura/uia) 시간창(일). 학습 extract(--days)와 서빙(serve.py)이 **반드시 공유**해야
#   train-serve skew가 없다. 친화도는 노출 시점(shown_at) 이전 이벤트로만 집계 → 타깃 누수 방지.
AFFINITY_WINDOW_DAYS = 90


def to_matrix(rows: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """라벨된 row dict 리스트 → (X 피처행렬, y 관련도, groups 그룹id).

    각 row: FEATURE_COLUMNS 키 + 'relevance'(0/1/2) + 'group'(=user·session 노출요청 id).
    LambdaMART는 그룹 연속성이 필요하므로 group으로 안정 정렬해 반환한다.
    """
    if not rows:
        return np.empty((0, len(FEATURE_COLUMNS))), np.empty(0), np.empty(0)
    order = np.argsort([r["group"] for r in rows], kind="stable")
    rows = [rows[i] for i in order]
    X = np.array([[float(r.get(c, 0.0)) for c in FEATURE_COLUMNS] for r in rows], dtype=float)
    y = np.array([int(r["relevance"]) for r in rows], dtype=int)
    groups = np.array([r["group"] for r in rows])
    return X, y, groups


def group_sizes(groups: np.ndarray) -> list[int]:
    """정렬된 groups → LightGBM group 파라미터(각 그룹 연속 길이). 순서 보존."""
    if groups.size == 0:
        return []
    sizes, cur, n = [], groups[0], 0
    for g in groups:
        if g == cur:
            n += 1
        else:
            sizes.append(n); cur, n = g, 1
    sizes.append(n)
    return sizes


def baseline_scores(rows: list[dict]) -> np.ndarray:
    """규칙 종합점수(rule_score)만으로 매긴 점수 — 개인화 없는 현행 랭킹 baseline."""
    return np.array([float(r.get(BASELINE_COLUMN, 0.0)) for r in rows], dtype=float)


# 실 PG 추출용(데이터 흐른 뒤 extract.py). 노출⋈이벤트(관련도) + 전역 인기도 + 유저 활동/친화도.
# #535: 친화도(ura/uia)는 노출 시점(shown_at) '이전' 이벤트로만 산출한다 — 라벨은 노출 후 30분 이벤트라,
#   같은 이벤트가 피처에도 들어가면 target leakage + train-serve skew(서빙은 노출 전 시점). ev가 shown_at을 노출.
EXTRACT_SQL = """
with ev as (   -- 노출별 최강 상호작용(ADD_CART>VIEW>none)을 관련도로
  select i.impression_id, i.user_id, i.session_id, i.recipe_id, i.rank,
         i.rule_score, i.score_stock, i.score_expiry, i.score_cost, i.request_ctx,
         i.shown_at,
         max(case e.event_type when 'ADD_CART' then 2 when 'VIEW' then 1 else 0 end) as relevance
    from activity.recipe_impression i
    left join activity.user_event e
      on e.user_id = i.user_id and e.session_id = i.session_id
     and e.recipe_id = i.recipe_id and e.recipe_id is not null
     and e.occurred_at between i.shown_at and i.shown_at + interval '30 minutes'
   where i.shown_at >= %(since)s
   group by i.impression_id, i.user_id, i.session_id, i.recipe_id, i.rank,
            i.rule_score, i.score_stock, i.score_expiry, i.score_cost, i.request_ctx, i.shown_at
),
pop as (   -- 레시피 전역 인기도 = 보존창 내 user_event + recipe_popularity(삭제 누적분, §4.1/PR#194)
           -- #535 잔여(수용): 레시피 단위 전역 집계라 노출 자기조회 1건이 섞이는 약한 누수는 남긴다.
           --   임프레션별 시간바운드는 비용 과다(전역 aggregate에 1-count 누수) + recipe_popularity는 스냅샷이라 시간여행 불가. 규모상 무시.
  select recipe_id, sum(v) as pop_view, sum(c) as pop_cart
    from (
      select recipe_id,
             count(*) filter (where event_type='VIEW')     as v,
             count(*) filter (where event_type='ADD_CART')  as c
        from activity.user_event where recipe_id is not null and occurred_at >= %(since)s
       group by recipe_id
      union all
      select recipe_id, view_cnt as v, add_cart_cnt as c from activity.recipe_popularity
    ) t
   group by recipe_id
),
ua as (   -- #535: 노출 시점(shown_at) '이전'까지의 유저 활동량 — 라벨창 이벤트 제외해 서빙과 정렬(impression 단위)
  select ev.impression_id, count(*) as user_events
    from ev
    join activity.user_event e3
      on e3.user_id = ev.user_id
     and e3.occurred_at >= %(since)s and e3.occurred_at < ev.shown_at
   group by ev.impression_id
),
ura as (   -- #535: 노출 시점(shown_at) '이전'에 이 레시피와 상호작용했는지 (누수·skew 방지, serve.py와 정렬).
           --   임프레션 단위 세미조인 — 옛 (user,recipe) 전역 distinct는 라벨 이벤트까지 포함해 누수였음.
  select distinct ev.impression_id
    from ev
    join activity.user_event e2
      on e2.user_id = ev.user_id and e2.recipe_id = ev.recipe_id and e2.recipe_id is not null
     and e2.occurred_at >= %(since)s and e2.occurred_at < ev.shown_at
),
liked_by_imp as (  -- #535: 임프레션별 유저 선호 재료 = 노출 '이전' ADD_CART 레시피 재료 + 대화 선호(스냅샷).
                   --   ⚠️ 대화선호(user_chat_pref)는 타임스탬프 없는 스냅샷이라 shown_at로 못 자름(잔여 skew, 별도 안건).
  select ev.impression_id, ri.item_id
    from ev
    join activity.user_event e
      on e.user_id = ev.user_id and e.event_type = 'ADD_CART'
     and e.occurred_at >= %(since)s and e.occurred_at < ev.shown_at
    join public.recipe_ingredient ri on ri.recipe_id = e.recipe_id and ri.item_id is not null
  union
  select ev.impression_id, unnest(cp.liked_item_ids)
    from ev
    join activity.user_chat_pref cp on cp.user_id = ev.user_id
),
uia as (   -- 유저-레시피 재료 친화도: 임프레션 레시피 재료 중 (노출 이전) 유저 선호재료와 겹치는 비율
  select ev.impression_id,
         count(*) filter (where lbi.item_id is not null)::float
           / nullif(count(*), 0) as user_ing_affinity
    from ev
    join public.recipe_ingredient ri on ri.recipe_id = ev.recipe_id and ri.item_id is not null
    left join liked_by_imp lbi on lbi.impression_id = ev.impression_id and lbi.item_id = ri.item_id
   group by ev.impression_id
)
select ev.*,
       coalesce(pop.pop_view,0)  as pop_view,
       coalesce(pop.pop_cart,0)  as pop_cart,
       coalesce(ua.user_events,0) as user_events,
       (ura.impression_id is not null)  as user_recipe_affinity,
       coalesce(uia.user_ing_affinity,0) as user_ing_affinity
  from ev
  left join pop on pop.recipe_id = ev.recipe_id
  left join ua  on ua.impression_id = ev.impression_id
  left join ura on ura.impression_id = ev.impression_id
  left join uia on uia.impression_id = ev.impression_id
"""


def raw_to_feature_rows(raw: list[dict]) -> list[dict]:
    """EXTRACT_SQL 원시행 → to_matrix가 먹는 피처행(파생피처 계산 + FEATURE_COLUMNS 채움).

    - pop_ctr = pop_cart / (pop_view + 1)  (전역 CTR, +1 스무딩)
    - user_activity = log1p(user_events) 정규화 근사
    - user_ing_affinity = 0 (2차 확장 전까지 결측=0)
    - group = (user_id, session_id) 노출요청 = LambdaMART 그룹
    """
    import math
    out = []
    for r in raw:
        pv, pc = float(r.get("pop_view", 0)), float(r.get("pop_cart", 0))
        out.append({
            "group": f"{r['user_id']}:{r['session_id']}",
            "relevance": int(r.get("relevance", 0)),
            "score_stock": float(r.get("score_stock") or 0.0),
            "score_expiry": float(r.get("score_expiry") or 0.0),
            "score_cost": float(r.get("score_cost") or 0.0),
            "rule_score": float(r.get("rule_score") or 0.0),
            "pop_view": pv, "pop_cart": pc, "pop_ctr": pc / (pv + 1.0),
            "user_activity": math.log1p(float(r.get("user_events", 0))),
            "user_recipe_affinity": 1.0 if r.get("user_recipe_affinity") else 0.0,
            "user_ing_affinity": float(r.get("user_ing_affinity") or 0.0),
            "budget_fit": _budget_fit(r.get("request_ctx")),
        })
    return out


def _budget_fit(request_ctx) -> float:
    """request_ctx(jsonb)에서 예산적합 추정 — 없으면 중립 0.5. 스키마 확정 시 정교화."""
    if isinstance(request_ctx, dict):
        v = request_ctx.get("budget_fit")
        if isinstance(v, (int, float)):
            return float(v)
    return 0.5
