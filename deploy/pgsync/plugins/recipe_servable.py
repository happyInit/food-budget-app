"""PGSync transform 플러그인 — recipe 조립 문서 → 배치 인덱서와 동일한 flat ES 문서.

schema.json(`deploy/pgsync/schema.json`)의 `plugins: ["RecipeServable"]` 로 등록.
PGSync 가 recipe(root) + recipe_ingredient(nested `ingredients[]`)를 조립한 뒤
문서마다 transform() 을 호출한다.

하는 일:
  1. servable 계산 — design.md §331 게이트를 그대로 재현(STATIC):
       source='10K'  AND  재료 ≥1개  AND  모든 재료 item_id 매칭(NULL 0건).
     price/nutrition 조인 없음 → recipe + recipe_ingredient 만의 함수라
     PGSync CDC 가 변경을 전부 포착(동적 리프레시 불필요).
  2. 평탄화 — 중첩 ingredients[] → ingredient_names[] / ingredient_item_ids[]
     (배치 index_recipes_es.py `_actions` 와 동일 shape → search.py 쿼리 무변경).
  3. 코퍼스(EPIS/COOKRCP01)는 색인하되 servable=false — Phase C 결정 '(나)':
     PGSync 의 None-skip 시맨틱(미검증)에 의존하지 않는 안전 경로.

⚠️ servable=false 문서도 색인된다 → search.py 는 반드시 {"term":{"servable":true}}
   로 필터해야 non-servable/코퍼스가 검색에 새지 않는다(컷오버 필수 변경, ③조각).
"""
from pgsync import plugin

# ES float 매핑 대상 — PG numeric(→ Decimal) 을 배치의 float() 캐스팅과 동일하게 처리.
_FLOAT_FIELDS = ("kcal", "carb_g", "protein_g", "fat_g")


class RecipeServable(plugin.Plugin):
    name = "RecipeServable"

    def transform(self, doc, **kwargs):
        ingredients = doc.get("ingredients") or []

        names = [
            i["ingredient_name"] for i in ingredients if i.get("ingredient_name")
        ]
        item_ids = [
            i["item_id"] for i in ingredients if i.get("item_id") is not None
        ]

        # STATIC 게이트 = source=10K + 재료≥1 + 미매칭 item_id 0건.
        #   all([]) 는 True 이므로 len>0 를 반드시 함께 검사(재료 0개 레시피 차단).
        doc["servable"] = (
            doc.get("source") == "10K"
            and len(ingredients) > 0
            and all(i.get("item_id") is not None for i in ingredients)
        )

        # 평탄화 — 배치 _actions 와 동일 필드/타입.
        doc["recipe_id"] = doc.get("id")
        doc["ingredient_names"] = names
        doc["ingredient_item_ids"] = [str(x) for x in item_ids]

        # numeric → float (ES float 매핑, Decimal 직렬화 회피).
        for f in _FLOAT_FIELDS:
            v = doc.get(f)
            doc[f] = float(v) if v is not None else None

        # 중첩 원본은 ES 로 내보내지 않음(flat 유지).
        doc.pop("ingredients", None)
        return doc
