"""공용 fixture. `client`는 lifespan을 실 DB 없이 띄우고, 각 테스트가 dependency_overrides로 fake 주입.

account/tests/conftest.py 복제 + JWT_SECRET 을 결정적 테스트값으로 고정(실 Bearer 검증 경로 테스트용).
env var 는 .env 파일보다 우선하므로, 로컬에 services/pantry/.env 가 있어도 테스트는 이 값을 쓴다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from tests.fakes import FakePool

TEST_JWT_SECRET = "test-secret-0123456789abcdef0123456789"  # ≥32B (프로덕션 요구 + PyJWT 경고 회피)


@pytest.fixture
def client(monkeypatch):
    # 주입 seam 덕에 핸들러는 override된 fake만 쓴다. lifespan의 풀 오픈만 no-op으로 막으면 실 DB 불요.
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)  # get_current_user 실검증 경로를 결정적으로
    monkeypatch.setattr(main_mod, "make_pg_pool", lambda settings: FakePool())
    with TestClient(main_mod.app) as c:
        yield c
    main_mod.app.dependency_overrides.clear()
