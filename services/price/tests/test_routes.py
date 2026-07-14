"""라우트 순서·모델 스모크 테스트 (DB 불필요)."""
from app.main import app
from app.models import CurrentPrice


def test_routes_registered_and_ordered():
    paths = [r.path for r in app.routes]
    assert "/api/prices/recommend" in paths
    assert "/api/prices/hotdeals" in paths
    assert "/api/prices/{item_id}" in paths
    assert "/api/prices/{item_id}/history" in paths
    # 정적 경로가 /{item_id} 보다 먼저 선언돼야 함(그래야 매칭됨)
    assert paths.index("/api/prices/recommend") < paths.index("/api/prices/{item_id}")
    assert paths.index("/api/prices/hotdeals") < paths.index("/api/prices/{item_id}")


def test_baseline_optional():
    cp = CurrentPrice(item_id=29, canonical_name="양파", category="채소", retail=[])
    assert cp.baseline is None
