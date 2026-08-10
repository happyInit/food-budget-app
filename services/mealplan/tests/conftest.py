"""공용 fixture. `client`는 lifespan을 실 DB 없이 띄우고, 각 테스트가 dependency_overrides로 fake 주입.
account/tests/conftest.py 를 복제(monkeypatch 대상 = mealplan main 의 make_pg_pool).

🔴 JWT_SECRET 은 **import 시점**에 넣는다(0-12) — jwt_secret 폴백 제거로 Settings() 가 env 없이는
   ConfigError 로 죽는다. tests/test_routes.py 가 Settings() 를 직접 만드는 곳도 이 값을 쓴다.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

TEST_JWT_SECRET = "test-secret-0123456789abcdef0123456789"  # ≥32자 (JWT_SECRET_MIN_LEN)
os.environ["JWT_SECRET"] = TEST_JWT_SECRET

import app.main as main_mod  # noqa: E402
from tests.fakes import FakePool  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    # 주입 seam 덕에 핸들러는 override된 fake만 쓴다. lifespan의 풀 오픈만 no-op으로 막으면 실 DB 불요.
    monkeypatch.setattr(main_mod, "make_pg_pool", lambda settings: FakePool())
    with TestClient(main_mod.app) as c:
        yield c
    main_mod.app.dependency_overrides.clear()
