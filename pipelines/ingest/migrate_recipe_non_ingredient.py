"""recipe_ingredient.is_non_ingredient 컬럼 — 비-재료 표시 (멱등).

**왜 컬럼인가.** gazetteer.STOP(물·얼음·이쑤시개…)은 "가정이 식비 재료로 사서 가격비교할
가치가 없는 이름"이라 **일부러 item_id 를 안 붙인다**(CONTEXT.md 비-재료). 그런데 servable
게이트가 `item_id IS NULL` 을 매칭 실패로 세는 바람에 **물이 들어갔다는 이유로 레시피가
검색에서 통째로 빠졌다**(실측 2026-07-21: 차단 2,760건 중 1,769건이 비-재료만이 원인, 그중
'물' 단독 1,520건). 게이트의 의도는 "모든 재료의 가격을 매길 수 있나"인데 STOP 품목은
정의상 가격을 안 매기기로 한 것들이라 실패로 세면 안 된다 — 정책 완화가 아니라 정의 오류.

게이트는 **두 곳에 중복 구현**돼 있다:
  · pipelines/ingest/index_recipes_es.py  — 배치(recipes, DR 폴백)의 SQL HAVING
  · deploy/pgsync/plugins/recipe_servable.py — CDC(recipes_pgsync, 실제 서빙)의 Python
후자는 pgsync 컨테이너에서 돌아 gazetteer.STOP 을 import 할 수 없다. STOP 을 복제하면 정본이
둘이 되므로, **적재 시점에 판정 결과를 컬럼으로 남기고 양쪽 게이트가 그 컬럼만 읽게** 한다.

migrate_quantity.py 처럼 standalone 멱등 마이그레이션 — apply_schema(drop/recreate) 경로와 분리.
사용:  python pipelines/ingest/migrate_recipe_non_ingredient.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _db import connect      # noqa: E402
from gazetteer import STOP   # noqa: E402

DDL = [
    # NOT NULL DEFAULT false — 기존 INSERT(load_recipe.py 의 COOKRCP01/EPIS 등)를 안 깬다.
    "ALTER TABLE recipe_ingredient "
    "ADD COLUMN IF NOT EXISTS is_non_ingredient boolean NOT NULL DEFAULT false",
]

# 기존 행 백필. STOP 판정은 load_10k_recipe.py 와 동일 규칙(원문 + 공백제거 양쪽 비교).
BACKFILL = """
update recipe_ingredient
   set is_non_ingredient = true
 where is_non_ingredient = false
   and (ingredient_name = any(%(stop)s) or replace(ingredient_name,' ','') = any(%(stop)s))
"""


def main() -> None:
    stop = sorted(STOP)
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SET lock_timeout = '15s'")   # 락 무한대기 방지(migrate_quantity.py 와 동일)
        for stmt in DDL:
            cur.execute(stmt)
        cur.execute(BACKFILL, {"stop": stop})
        backfilled = cur.rowcount
        conn.commit()

        cur.execute("select count(*) from recipe_ingredient where is_non_ingredient")
        flagged = cur.fetchone()[0]
        cur.execute(
            """select count(*) from (
                 select r.id from recipe r join recipe_ingredient ri on ri.recipe_id = r.id
                  where r.source = '10K'
                  group by r.id
                 having count(*) filter (where ri.item_id is null and not ri.is_non_ingredient) = 0
                    and count(*) filter (where not ri.is_non_ingredient) > 0
               ) t"""
        )
        servable = cur.fetchone()[0]
    print(f"is_non_ingredient: 이번 백필 {backfilled:,}행 · 총 표시 {flagged:,}행")
    print(f"신 게이트 기준 10K servable: {servable:,}건")


if __name__ == "__main__":
    main()
