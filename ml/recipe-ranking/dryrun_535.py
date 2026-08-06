"""#535 오프라인 드라이런 — 누수 픽스 '전/후' 비교 (PR 전 검증, 로컬 실행).

실제 PG에서 **옛(누수) extract**와 **고친 extract**(`features.EXTRACT_SQL`)를 각각
추출→학습→평가하고, NDCG/MAP/MRR + `user_recipe_affinity`(ura) 피처 중요도 비중을
나란히 출력한다.

기대(픽스가 맞다는 증거):
  ① 고친 쪽 지표(NDCG/MAP/MRR)가 **낮아짐**  = 누수로 부풀려졌던 값이 정직해짐(실서빙 저하 아님).
  ② `ura` 피처 중요도 비중이 **급락**        = 라벨을 예측하던 누수 신호가 사라짐.
→ 이 표를 그대로 PR 본문에 붙이면 "고쳤고 지표 하락은 예상대로"의 근거가 된다.

실행:
    cd ml/recipe-ranking
    pip install -r requirements.txt          # numpy, lightgbm, psycopg
    python dryrun_535.py --days 90
환경변수(레포 루트 .env 자동 로드): PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD.

주의: 프로덕션 무변경(읽기 전용 추출 + 로컬 학습). 배포/서빙 모델은 건드리지 않는다.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone

import numpy as np  # noqa: F401 (features/train가 요구)

import evaluate
import features
import train
from features import EXTRACT_SQL as FIXED_SQL
from features import FEATURE_COLUMNS, raw_to_feature_rows, to_matrix

# ── 옛(누수) extract — 픽스 전 버전. ura/uia/ua가 노출 시점(shown_at) 경계 없이 시간창 전체를 집계. ──
LEAKED_SQL = r"""
with ev as (
  select i.impression_id, i.user_id, i.session_id, i.recipe_id, i.rank,
         i.rule_score, i.score_stock, i.score_expiry, i.score_cost, i.request_ctx,
         max(case e.event_type when 'ADD_CART' then 2 when 'VIEW' then 1 else 0 end) as relevance
    from activity.recipe_impression i
    left join activity.user_event e
      on e.user_id = i.user_id and e.session_id = i.session_id
     and e.recipe_id = i.recipe_id and e.recipe_id is not null
     and e.occurred_at between i.shown_at and i.shown_at + interval '30 minutes'
   where i.shown_at >= %(since)s
   group by i.impression_id, i.user_id, i.session_id, i.recipe_id, i.rank,
            i.rule_score, i.score_stock, i.score_expiry, i.score_cost, i.request_ctx
),
pop as (
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
ua as (
  select user_id, count(*) as user_events
    from activity.user_event where occurred_at >= %(since)s group by user_id
),
ura as (
  select distinct user_id, recipe_id from activity.user_event
   where recipe_id is not null and occurred_at >= %(since)s
),
u_ings as (
  select distinct user_id, item_id from (
    select e.user_id, ri.item_id
      from activity.user_event e
      join public.recipe_ingredient ri on ri.recipe_id = e.recipe_id and ri.item_id is not null
     where e.event_type = 'ADD_CART' and e.occurred_at >= %(since)s
    union
    select user_id, unnest(liked_item_ids) as item_id from activity.user_chat_pref
  ) t where item_id is not null
),
uia as (
  select ev.impression_id,
         count(*) filter (where ui.item_id is not null)::float
           / nullif(count(*), 0) as user_ing_affinity
    from ev
    join public.recipe_ingredient ri on ri.recipe_id = ev.recipe_id and ri.item_id is not null
    left join u_ings ui on ui.user_id = ev.user_id and ui.item_id = ri.item_id
   group by ev.impression_id
)
select ev.*,
       coalesce(pop.pop_view,0)  as pop_view,
       coalesce(pop.pop_cart,0)  as pop_cart,
       coalesce(ua.user_events,0) as user_events,
       (ura.user_id is not null)  as user_recipe_affinity,
       coalesce(uia.user_ing_affinity,0) as user_ing_affinity
  from ev
  left join pop on pop.recipe_id = ev.recipe_id
  left join ua  on ua.user_id   = ev.user_id
  left join ura on ura.user_id  = ev.user_id and ura.recipe_id = ev.recipe_id
  left join uia on uia.impression_id = ev.impression_id
"""


def _connect():
    import psycopg
    ci = (f"host={os.environ.get('PGHOST', '192.168.0.8')} port={os.environ.get('PGPORT', '5432')} "
          f"dbname={os.environ.get('PGDATABASE', 'foodbudget')} user={os.environ.get('PGUSER', 'fbapp')} "
          f"password={os.environ.get('PGPASSWORD', '')}")
    return psycopg.connect(ci, connect_timeout=5)


def _extract(conn, sql, since):
    with conn.cursor() as cur:
        cur.execute(sql, {"since": since})
        cols = [d.name for d in cur.description]
        raw = [dict(zip(cols, r)) for r in cur.fetchall()]
    return raw_to_feature_rows(raw)


def _importance_share(model) -> dict:
    """FEATURE_COLUMNS별 중요도 '비중'(합=1)."""
    est = getattr(model, "_m", model)
    imp = getattr(est, "feature_importances_", None)
    if imp is None:
        return {}
    tot = float(np.sum(imp)) or 1.0
    return {c: float(v) / tot for c, v in zip(FEATURE_COLUMNS, imp)}


def _run(sql, conn, since, seed=0):
    rows = _extract(conn, sql, since)
    groups = sorted({r["group"] for r in rows})
    if len(groups) < 4:
        return None
    cut = max(1, int(len(groups) * 0.75))
    tr_g, te_g = set(groups[:cut]), set(groups[cut:])
    tr = [r for r in rows if r["group"] in tr_g]
    te = [r for r in rows if r["group"] in te_g]
    Xtr, ytr, gtr = to_matrix(tr)
    Xte, yte, gte = to_matrix(te)
    model = train.train(Xtr, ytr, gtr, random_state=seed)
    res = evaluate.compare(yte, model.predict(Xte), features.baseline_scores(te), gte, k=10)
    return {"n_rows": len(rows), "n_groups": len(groups), "m": res["model"], "imp": _importance_share(model)}


def main() -> int:
    ap = argparse.ArgumentParser(description="#535 누수 픽스 전/후 오프라인 비교")
    ap.add_argument("--days", type=int, default=features.AFFINITY_WINDOW_DAYS)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    try:
        from dotenv import load_dotenv  # noqa: PLC0415
        load_dotenv()
    except Exception:  # noqa: BLE001
        pass

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    print(f"[#535 dryrun] since={since:%Y-%m-%d}  days={args.days}\n")

    with _connect() as conn:
        leaked = _run(LEAKED_SQL, conn, since, args.seed)
        fixed = _run(FIXED_SQL, conn, since, args.seed)

    if leaked is None or fixed is None:
        print("데이터 부족(테스트 그룹 < 4) — 임프레션/이벤트가 더 쌓인 뒤 재실행하세요.")
        return 1

    print(f"추출: 옛={leaked['n_rows']}행/{leaked['n_groups']}그룹 · 고친={fixed['n_rows']}행/{fixed['n_groups']}그룹\n")
    print(f"{'지표':<10}{'옛(누수)':>12}{'고친':>12}{'Δ':>12}")
    print("-" * 46)
    for k in ("ndcg@k", "map@k", "mrr"):
        lo, fi = leaked["m"][k], fixed["m"][k]
        print(f"{k:<10}{lo:>12.4f}{fi:>12.4f}{fi - lo:>+12.4f}")
    lu = leaked["imp"].get("user_recipe_affinity", 0.0)
    fu = fixed["imp"].get("user_recipe_affinity", 0.0)
    print("-" * 46)
    print(f"{'ura 중요도':<10}{lu:>11.1%}{fu:>12.1%}{(fu - lu) * 100:>+11.1f}p")
    print()
    print("[해석] 고친 쪽에서 NDCG 등이 낮아지고 ura 중요도가 급락하면 → 누수 제거가 정상 작동한 증거.")
    print("       (지표 하락 = 부풀림 제거이지 실서빙 품질 저하가 아님 → 재기준선)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
