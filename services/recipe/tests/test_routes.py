"""라우트·모델 스모크 테스트 (DB 불필요 — lifespan 미기동)."""
from app.main import app
from app.models import Nutrition, RecipeCard, RecipeDetail


def test_routes_registered():
    paths = {r.path for r in app.routes}
    assert "/metrics" in paths
    assert "/health" in paths
    assert "/api/recipes" in paths
    assert "/api/recipes/{recipe_id}" in paths
    assert "/metrics" not in app.openapi()["paths"]


def test_models_optional_fields():
    # 데이터 티어에 null이 흔한 필드들이 Optional인지
    card = RecipeCard(id=1, name="김치찌개", source="10K")
    assert card.category is None
    detail = RecipeDetail(
        id=1, source="10K", name="김치찌개", nutrition=Nutrition(), ingredients=[], steps=[]
    )
    assert detail.nutrition.kcal is None


def test_detail_query_excludes_unnamed_ingredient_rows():
    """이름 없는 재료 행은 조회에서 제외한다 — 유저 화면에 **빈 재료 줄**로 보였다.

    `ner_status='RAW'` 행은 크롤러가 쪼개지 못한 재료 덩어리를 `ingredient_raw` 에 통째로
    담고 `ingredient_name` 은 비워 둔다. 실측(2026-07-30): **빈 이름 1,143행이 전부 RAW**
    (CRAWLER·LABELED·NER_PARSED 는 0건)이고 그중 1,142개 레시피는 CRF 구조화 결과도 함께
    가진다 → 레시피마다 재료 목록에 빈 줄이 하나씩 떴다.

    행을 지우지 않고 조회에서 거르는 이유: `ingredient_raw` 원문은 재백필·감사에 필요하다.

    ⚠️ 재료비(`ingredient_cost_total`)는 불변이다 — 빈 행은 `item_id IS NULL` 이라 단가 조회
       대상에 안 들어가고 `basis='no_price'` 로 누적되지 않는다.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app" / "queries.py").read_text()
    assert "coalesce(btrim(ingredient_name), '') <> ''" in src, (
        "빈 이름 재료 행 필터가 사라졌다 — 레시피 상세에 빈 줄이 다시 보인다"
    )
