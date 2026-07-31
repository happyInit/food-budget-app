"""CI 스모크 테스트 — 앱 메타데이터 + 헬스 엔드포인트 (주입 seam으로 실 DB 불필요).

CI 파이프라인의 pytest 게이트가 실제로 도는지 확인하기 위한 최소 테스트.
conftest 의 `client` fixture 가 make_pg_pool 을 FakePool 로 대체해 DB 없이 앱을 띄운다.
"""
from __future__ import annotations

import app.main as main_mod


def test_app_metadata():
    assert main_mod.app.title == "Account Service"
    assert main_mod.app.version == "0.1.0"


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "account"}
