"""recipe/recipe_ingredient(PG) → recipes(ES, nori) 레시피 검색 인덱서.

gazetteer 재실행 불필요: load_10k_recipe.py가 적재 시점에 이미 item_id를
해소해뒀음(recipe_ingredient.item_id) — 여기선 SQL JOIN만 한다.

매번 index drop→recreate 후 전량 재색인(현재 규모 ~1만 건대라 alias-swap 등
무중단 기법은 과설계). load_10k_recipe.py 재적재 후에는 이 스크립트도 수동
재실행 필요 — 자동 훅 연결은 스코프 밖.

서빙 품질 게이트 적용(design.md §10): source='10K'만 + strict(미매칭 재료 0)
레시피만 색인 — 상세는 QUERY 주석.
"""
import sys
from pathlib import Path

from elasticsearch.helpers import bulk

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stream"))
from _db import connect, es_client  # noqa: E402
from _observability import get_pipeline_logger  # noqa: E402

INDEX = "recipes"
COMPONENT = "poller-es-recipes"
log = get_pipeline_logger(COMPONENT)

SETTINGS = {
    "settings": {
        "number_of_replicas": 0,   # 단일노드 ES → 리플리카 미할당(yellow) 회피 = green
        "analysis": {
            "tokenizer": {
                "nori_mixed": {"type": "nori_tokenizer", "decompound_mode": "mixed"}
            },
            "analyzer": {
                "korean": {
                    "type": "custom",
                    "tokenizer": "nori_mixed",
                    "filter": ["nori_readingform", "lowercase"],
                }
            },
        }
    },
    "mappings": {
        "properties": {
            "recipe_id": {"type": "long"},
            "name": {"type": "text", "analyzer": "korean"},
            "category": {"type": "keyword"},
            "cook_method": {"type": "keyword"},
            "cooking_time": {"type": "keyword"},
            "level_nm": {"type": "keyword"},
            "serving": {"type": "keyword"},
            "kcal": {"type": "float"},
            "carb_g": {"type": "float"},
            "protein_g": {"type": "float"},
            "fat_g": {"type": "float"},
            "ingredient_names": {"type": "text", "analyzer": "korean"},
            "ingredient_item_ids": {"type": "keyword"},
            "servable": {"type": "boolean"},  # PGSync 인덱스와 shape 통일 — 배치는 게이트 통과분만이라 항상 true
            "source": {"type": "keyword"},
            "image_url": {"type": "keyword", "index": False},
        }
    },
}

# 서빙 품질 게이트 (design.md §10, 2026-07-15):
#   · source='10K'  — 유저 웹 서빙 대상은 만개의레시피만 (EPIS/COOKRCP01은 학습 코퍼스라 제외)
#   · strict        — 미매칭 재료(item_id IS NULL)가 1개라도 있으면 레시피 통째 non-servable.
#                     JOIN(=재료 0개 레시피 제외) + HAVING(=미매칭 0) 조합으로 표현.
#   불량 행은 PG에 그대로 둔다(재매칭·백필용) — 색인에서만 빼는 mark-and-filter.
#   완화 옵션(design.md §10, 미채택): having 을 매칭률 ≥0.8 로 바꾸면 "미매칭 재료 ≤1개 허용".
QUERY = """
select r.id, r.name, r.category, r.cook_method, r.cooking_time, r.level_nm, r.serving,
       r.kcal, r.carb_g, r.protein_g, r.fat_g, r.source, r.image_url,
       array_remove(array_agg(distinct ri.ingredient_name), null) as ing_names,
       array_remove(array_agg(distinct ri.item_id), null) as item_ids
from recipe r join recipe_ingredient ri on ri.recipe_id = r.id
where r.source = '10K'
group by r.id
having count(*) filter (where ri.item_id is null) = 0
"""


def _actions(rows):
    for row in rows:
        (rid, name, category, cook_method, cooking_time, level_nm, serving,
         kcal, carb_g, protein_g, fat_g, source, image_url, ing_names, item_ids) = row
        yield {
            "_index": INDEX,
            "_id": rid,
            "_source": {
                "recipe_id": rid,
                "name": name,
                "category": category,
                "cook_method": cook_method,
                "cooking_time": cooking_time,
                "level_nm": level_nm,
                "serving": serving,
                "kcal": float(kcal) if kcal is not None else None,
                "carb_g": float(carb_g) if carb_g is not None else None,
                "protein_g": float(protein_g) if protein_g is not None else None,
                "fat_g": float(fat_g) if fat_g is not None else None,
                "ingredient_names": ing_names,
                "ingredient_item_ids": [str(i) for i in item_ids],
                "servable": True,   # HAVING 게이트로 servable 만 색인 → 항상 true(search.py 필터 parity)
                "source": source,
                "image_url": image_url,
            },
        }


def main():
    es = es_client()
    if es.indices.exists(index=INDEX):
        es.indices.delete(index=INDEX)
    es.indices.create(index=INDEX, **SETTINGS)

    with connect() as conn, conn.cursor() as cur:
        cur.execute(QUERY)
        rows = cur.fetchall()

    ok, errors = bulk(es, _actions(rows))
    item_id_hit = sum(1 for r in rows if r[-1])
    print(f"색인: 10K servable {ok}건 (오류 {len(errors)}건) — "
          f"item_id 매칭 {item_id_hit}/{len(rows)} (strict 게이트라 전건 매칭)")
    log.info(
        "recipe search index rebuild completed",
        extra={
            "event": "es_reindex_succeeded",
            "component": COMPONENT,
            "source": "10K",
            "result": "success",
            "record_count": ok,
        },
    )


if __name__ == "__main__":
    main()
