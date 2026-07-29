"""라우트 순서·모델 스모크 테스트 (DB 불필요)."""
from app.main import app
from app.models import CurrentPrice


def test_routes_registered_and_ordered():
    paths = [r.path for r in app.routes]
    assert "/metrics" in paths
    assert "/api/prices/recommend" in paths
    assert "/api/prices/hotdeals" in paths
    assert "/api/prices/{item_id}" in paths
    assert "/api/prices/{item_id}/history" in paths
    # 정적 경로가 /{item_id} 보다 먼저 선언돼야 함(그래야 매칭됨)
    assert paths.index("/api/prices/recommend") < paths.index("/api/prices/{item_id}")
    assert paths.index("/api/prices/hotdeals") < paths.index("/api/prices/{item_id}")
    assert "/metrics" not in app.openapi()["paths"]


def test_baseline_optional():
    cp = CurrentPrice(item_id=29, canonical_name="양파", category="채소", retail=[])
    assert cp.baseline is None


# ── #29·#30 최저가 관심 ──
def test_watch_routes_registered_before_item_id():
    """`/api/prices/watch` 가 `/{item_id}` 뒤에 선언되면 item_id="watch" 로 잡혀 422가 난다."""
    paths = [r.path for r in app.routes]
    assert "/api/prices/watch" in paths
    assert "/api/prices/watch/{item_id}" in paths
    assert paths.index("/api/prices/watch") < paths.index("/api/prices/{item_id}")
    assert paths.index("/api/prices/watch/{item_id}") < paths.index("/api/prices/{item_id}")


def test_watch_requires_auth():
    """user_id를 JWT에서만 받는다(A01) — 토큰 없으면 401이고, 등록이 일어나선 안 된다."""
    from fastapi.testclient import TestClient

    # lifespan을 띄우지 않는다 — 인증 거부가 DB·풀 접근보다 **먼저** 일어나야 한다는 뜻이기도 하다.
    client = TestClient(app)
    assert client.post("/api/prices/watch", json={"item_id": 1}).status_code == 401
    assert client.delete("/api/prices/watch/1").status_code == 401
    assert client.get("/api/prices/watch").status_code == 401


def test_watch_rejects_user_id_in_body():
    """바디의 user_id는 스키마에 없어 무시된다 — 남의 관심 목록을 조작할 수 없다."""
    from app.models import WatchRequest

    req = WatchRequest.model_validate({"item_id": 5, "user_id": 999})
    assert not hasattr(req, "user_id")
    assert req.item_id == 5


def test_watch_rejects_non_positive_item_id():
    import pytest
    from pydantic import ValidationError

    from app.models import WatchRequest

    with pytest.raises(ValidationError):
        WatchRequest(item_id=0)
