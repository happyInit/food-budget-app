"""Chat 서비스의 공통 운영 endpoint 등록 검증."""

from app.main import app


def test_metrics_route_is_registered_but_hidden_from_openapi():
    paths = {route.path for route in app.routes}
    assert "/metrics" in paths
    assert "/metrics" not in app.openapi()["paths"]
