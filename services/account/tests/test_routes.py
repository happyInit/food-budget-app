"""라우터 골든 테스트 — 주입 seam으로 실 DB·실 JWT 없이 핸들러를 통째 검증.
★ 두 명이 새 서비스 만들 때 이 override 패턴을 복사한다:
   app.dependency_overrides[get_conn] = lambda: FakeConn([...])  → DB 없이 쿼리 결과 주입
   app.dependency_overrides[get_current_user] = lambda: 7        → 인증 통과 가장
"""
from __future__ import annotations

from datetime import date

from psycopg.errors import UniqueViolation

import app.main as main_mod
from app.context import get_conn, get_current_user, get_security
from app.security import Security
from tests.fakes import FakeConn

SEC = Security("test-secret")
OV = main_mod.app.dependency_overrides


def test_signup_created(client):
    conn = FakeConn(responses=[(42,)])                 # INSERT ... RETURNING id
    OV[get_conn] = lambda: conn
    OV[get_security] = lambda: SEC
    r = client.post("/api/auth/signup",
                    json={"email": "a@b.com", "password": "hunter2!!", "nickname": "kim"})
    assert r.status_code == 201
    assert r.json() == {"userId": 42}
    assert "insert into account.app_user" in conn.executed[0][0]


def test_signup_duplicate_email_409(client):
    OV[get_conn] = lambda: FakeConn(raise_exc=UniqueViolation("dup"))
    OV[get_security] = lambda: SEC
    r = client.post("/api/auth/signup",
                    json={"email": "a@b.com", "password": "hunter2!!", "nickname": "kim"})
    assert r.status_code == 409


def test_login_ok_returns_tokens(client):
    h = SEC.hash_password("hunter2!!")
    OV[get_conn] = lambda: FakeConn(responses=[(7, h, "local")])   # (id, password_hash, provider)
    OV[get_security] = lambda: SEC
    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "hunter2!!"})
    assert r.status_code == 200
    assert SEC.verify_access(r.json()["access_token"]) == 7        # 발급 토큰이 실제로 user 7


def test_login_bad_password_401(client):
    h = SEC.hash_password("right")
    OV[get_conn] = lambda: FakeConn(responses=[(7, h, "local")])
    OV[get_security] = lambda: SEC
    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong"})
    assert r.status_code == 401


def test_me_requires_auth(client):
    # get_current_user 미오버라이드 → 실제 Bearer 검증 → 토큰 없음 → 401
    assert client.get("/api/users/me").status_code == 401


def test_me_with_injected_user(client):
    OV[get_conn] = lambda: FakeConn(responses=[(7, "a@b.com", "kim", "local")])
    OV[get_current_user] = lambda: 7
    r = client.get("/api/users/me")
    assert r.status_code == 200
    assert r.json() == {"id": 7, "email": "a@b.com", "nickname": "kim", "provider": "local"}


def test_put_budget(client):
    OV[get_conn] = lambda: FakeConn(responses=[(date(2026, 7, 1), 400000)])
    OV[get_current_user] = lambda: 7
    r = client.put("/api/users/budget", json={"amount": 400000})
    assert r.status_code == 200
    assert r.json() == {"month": "2026-07-01", "amount": 400000}
