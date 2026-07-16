"""라우터 골든 테스트 — 주입 seam으로 실 DB·실 JWT 없이 핸들러를 통째 검증.
★ 두 명이 새 서비스 만들 때 이 override 패턴을 복사한다:
   app.dependency_overrides[get_conn] = lambda: FakeConn([...])  → DB 없이 쿼리 결과 주입
   app.dependency_overrides[get_current_user] = lambda: 7        → 인증 통과 가장
FakeConn 응답은 dict (풀 row_factory=dict_row와 동일 shape).
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


def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text


def test_signup_created(client):
    conn = FakeConn(responses=[{"id": 42}])            # INSERT ... RETURNING id
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
    OV[get_conn] = lambda: FakeConn(responses=[{"id": 7, "password_hash": h, "provider": "local"}])
    OV[get_security] = lambda: SEC
    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "hunter2!!"})
    assert r.status_code == 200
    assert SEC.verify_access(r.json()["access_token"]) == 7        # 발급 토큰이 실제로 user 7


def test_login_bad_password_401(client):
    h = SEC.hash_password("right")
    OV[get_conn] = lambda: FakeConn(responses=[{"id": 7, "password_hash": h, "provider": "local"}])
    OV[get_security] = lambda: SEC
    r = client.post("/api/auth/login", json={"email": "a@b.com", "password": "wrong"})
    assert r.status_code == 401


def test_me_requires_auth(client):
    # get_current_user 미오버라이드 → 실제 Bearer 검증 → 토큰 없음 → 401
    assert client.get("/api/users/me").status_code == 401


def test_me_with_injected_user(client):
    OV[get_conn] = lambda: FakeConn(
        responses=[{"id": 7, "email": "a@b.com", "nickname": "kim", "provider": "local"}])
    OV[get_current_user] = lambda: 7
    r = client.get("/api/users/me")
    assert r.status_code == 200
    assert r.json() == {"id": 7, "email": "a@b.com", "nickname": "kim", "provider": "local"}


def test_put_budget(client):
    OV[get_conn] = lambda: FakeConn(responses=[{"month": date(2026, 7, 1), "amount": 400000}])
    OV[get_current_user] = lambda: 7
    r = client.put("/api/users/budget", json={"amount": 400000})
    assert r.status_code == 200
    assert r.json() == {"month": "2026-07-01", "amount": 400000}


# ── 제외 재료 (회피 재료) ──
def test_list_excluded_owner_scoped(client):
    conn = FakeConn(responses=[{"item_id": 10, "name": "오이"}, {"item_id": 20, "name": "고수"}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/users/excluded-items")
    assert r.status_code == 200
    assert [x["name"] for x in r.json()] == ["오이", "고수"]
    sql, params = conn.executed[0]
    assert "from account.user_excluded_item" in sql and "user_id = %s" in sql   # A01
    assert params == (7,)


def test_add_excluded_upsert(client):
    conn = FakeConn(responses=[{"item_id": 10, "name": "오이"}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/users/excluded-items", json={"item_id": 10, "name": "오이"})
    assert r.status_code == 201
    assert r.json() == {"item_id": 10, "name": "오이"}
    sql, params = conn.executed[0]
    assert "insert into account.user_excluded_item" in sql
    assert params[0] == 7                              # user_id from JWT (바디 아님, A01)


def test_add_excluded_unknown_item_404(client):
    from psycopg.errors import ForeignKeyViolation
    OV[get_conn] = lambda: FakeConn(raise_exc=ForeignKeyViolation("no item_master"))
    OV[get_current_user] = lambda: 7
    r = client.post("/api/users/excluded-items", json={"item_id": 999999, "name": "x"})
    assert r.status_code == 404


def test_remove_excluded_owner_scoped_204(client):
    conn = FakeConn(responses=[{"item_id": 10}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.delete("/api/users/excluded-items/10")
    assert r.status_code == 204
    assert conn.executed[0][1] == (7, 10)              # (user_id, item_id) 소유자 스코프


def test_remove_excluded_not_found_404(client):
    conn = FakeConn(responses=[])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    assert client.delete("/api/users/excluded-items/10").status_code == 404


def test_excluded_requires_auth(client):
    assert client.get("/api/users/excluded-items").status_code == 401


def test_delete_me_owner_scoped_204(client):
    conn = FakeConn(responses=[{"id": 7}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.delete("/api/users/me")
    assert r.status_code == 204
    sql, params = conn.executed[0]
    assert "delete from account.app_user" in sql and params == (7,)   # JWT uid 로만


def test_delete_me_requires_auth(client):
    assert client.delete("/api/users/me").status_code == 401
