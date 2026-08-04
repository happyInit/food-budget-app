"""PGSync transform 플러그인 — recipebook.shared_recipe(유저 발행 레시피) → flat ES 문서.

schema.json(`deploy/pgsync/schema.json`)의 `plugins: ["SharedRecipe"]` 로 등록.
PGSync 가 recipebook.shared_recipe(root, 자식 테이블 없음 — 재료가 jsonb 컬럼) 문서마다
transform() 을 호출한다.

하는 일:
  1. 평탄화 — jsonb ingredients[] → ingredient_names[] (nori 형태소 분석 대상 텍스트).
     shape: [{"name": "돼지고기", "quantity": "300g"}, ...] (services/recipebook/app/models.py
     `IngredientItem`). item_id 는 저장/검색되지 않는다 — 상세 서빙 시 read-time 재매칭 파생값이라
     recipe_servable.py 처럼 ingredient_item_ids 를 만들지 않는다.
  2. 중첩 원본 ingredients 제거 — flat 유지(recipe_servable.py 와 동일 이유).

  컬럼 선택 — schema.json 의 `columns` 에서 검색·목록 카드에 필요한 것만 가져온다
  (id, title, image_url, ingredients, origin, share_token, published_at). user_id(발행자
  식별자)·steps(조리 본문)·user_recipe_id(파생 FK)·source_url(목록에 안 쓰임) 은 제외해
  문서를 최소화한다. 특히 ingredients 는 본 transform 이 ingredient_names 를 만들 때만
  내부적으로 소비하고, 완성 문서에선 pop 된다.

  share_token 은 유지한다 — 공개 발행 목록 카드의 계약(SharedRecipeCard)이 `share_token`
  을 담아 `/shared/<token>` 공개 상세 링크를 만드는데, B단계(읽기 전환)에서 이 카드 데이터를
  ES 로 채울 때 이 필드가 필요하다.

why shared_recipe (A단계 설계 결정): 발행=insert → 검색 등장 / 취소=delete → 소멸로 CDC 시맨틱이
정확히 맞는다. 또 user_recipe 에는 비공개 레시피도 있어서 is_public 필터로 거르면 그 필터가 한 번
깨질 때 남의 비공개 레시피가 검색에 노출된다 — 안 넣는 게 맞다. 따라서 서로 다른 인덱스
(user_recipes_live)로 가므로 이 플러그인엔 recipe_servable.py 의 servable 게이트가 필요 없다
(그것은 source='10K' 크롤링 레시피용 게이트다).

⚠️ ingredients 는 nullable jsonb 라 NULL 이거나 리스트가 아닐 수 있다 — 방어한다(None → []).
"""
from pgsync import plugin


class SharedRecipe(plugin.Plugin):
    name = "SharedRecipe"

    def transform(self, doc, **kwargs):
        ingredients = doc.get("ingredients") or []

        # 리스트가 아닌 값(NULL 이 아닌데 jsonb 가 깨진 경우 등) 방어 — [] 로 강등.
        if not isinstance(ingredients, list):
            ingredients = []

        # name 만 추출. 반드시 문자열이어야 하고, 공백만·빈·None 은 걸러낸다.
        ingredient_names = [
            i["name"] for i in ingredients
            if isinstance(i, dict) and isinstance(i.get("name"), str) and i["name"].strip()
        ]
        doc["ingredient_names"] = ingredient_names

        # 중첩 원본은 ES 로 내보내지 않음 — flat 필드만 유지(recipe_servable.py 와 동일 정책).
        doc.pop("ingredients", None)
        return doc
