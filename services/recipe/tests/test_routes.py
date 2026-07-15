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
