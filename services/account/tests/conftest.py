"""공용 fixture. `client`는 lifespan을 실 DB 없이 띄우고, 각 테스트가 dependency_overrides로 fake 주입.

🔴 JWT_SECRET 은 **import 시점**에 넣는다(0-12). jwt_secret 의 placeholder 폴백을 없앴으므로
   Settings() 는 env 없이는 ConfigError 로 죽는다 — fixture(=테스트 실행 시점)로는 늦은 경우
   (모듈 전역 Settings·import 시 평가)가 있어 conftest 모듈 로드 시점에 세팅한다.
   os.environ 을 **덮어쓴다**(setdefault 아님) — 셸에 실 비밀이 export 돼 있어도 테스트는 격리된다.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

TEST_JWT_SECRET = "test-secret-0123456789abcdef0123456789"  # ≥32자 (JWT_SECRET_MIN_LEN)
os.environ["JWT_SECRET"] = TEST_JWT_SECRET

import app.main as main_mod  # noqa: E402  (env 세팅 후 import — 전역 Settings 대비)
from tests.fakes import FakePool  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    # 주입 seam 덕에 핸들러는 override된 fake만 쓴다. lifespan의 풀 오픈만 no-op으로 막으면 실 DB 불요.
    monkeypatch.setattr(main_mod, "make_pg_pool", lambda settings: FakePool())
    with TestClient(main_mod.app) as c:
        yield c
    main_mod.app.dependency_overrides.clear()
