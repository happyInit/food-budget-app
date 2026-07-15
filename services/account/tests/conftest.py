"""공용 fixture. `client`는 lifespan을 실 DB 없이 띄우고, 각 테스트가 dependency_overrides로 fake 주입."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from tests.fakes import FakePool


@pytest.fixture
def client(monkeypatch):
    # 주입 seam 덕에 핸들러는 override된 fake만 쓴다. lifespan의 풀 오픈만 no-op으로 막으면 실 DB 불요.
    monkeypatch.setattr(main_mod, "make_pg_pool", lambda settings: FakePool())
    with TestClient(main_mod.app) as c:
        yield c
    main_mod.app.dependency_overrides.clear()
