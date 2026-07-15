"""라우터 골든 테스트 — 주입 seam으로 실 DB·실 JWT 없이 핸들러를 통째 검증(account 패턴 복제).
   app.dependency_overrides[get_conn] = lambda: FakeConn([...])  → DB 없이 쿼리 결과 주입
   app.dependency_overrides[get_current_user] = lambda: 7        → 인증 통과 가장
FakeConn 응답은 dict(풀 row_factory=dict_row와 동일 shape).

커버: (a) SQL 매핑·정상응답, (b) 에러코드(409/404), (c) 인증 없이 401,
      (d) 소유권(남의 행 삭제 → None → 404, WHERE user_id 바인딩 검증).
"""
from __future__ import annotations

from psycopg.errors import ForeignKeyViolation, UniqueViolation

import app.main as main_mod
from app.context import get_conn, get_current_user
from tests.fakes import FakeConn

OV = main_mod.app.dependency_overrides


def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text


# ── #20 GET /api/recipes/book ──────────────────────────────────────────────
def test_list_books_maps_join(client):
    rows = [
        {"id": 1, "recipe_id": 100, "name": "김치찌개",
         "image_url": "http://img/1.jpg", "cooking_time": "30분 이내", "level_nm": "초급"},
        {"id": 2, "recipe_id": 200, "name": "된장국",
         "image_url": None, "cooking_time": None, "level_nm": None},
    ]
    conn = FakeConn(responses=rows)
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/recipes/book")
    assert r.status_code == 200
    body = r.json()
    assert [b["id"] for b in body["books"]] == [1, 2]
    assert body["books"][0]["name"] == "김치찌개"
    assert body["books"][1]["cooking_time"] is None       # null 컬럼 허용
    # 소유권(A01): JOIN 쿼리에 WHERE b.user_id = %s + JWT user_id(7) 바인딩
    sql, params = conn.executed[0]
    assert "join public.recipe" in sql.lower()
    assert "where b.user_id = %s" in sql.lower()
    assert params == (7,)


def test_list_requires_auth(client):
    # get_current_user 미오버라이드 → 실제 Bearer 검증 → 토큰 없음 → 401
    assert client.get("/api/recipes/book").status_code == 401


# ── #21 POST /api/recipes/book ─────────────────────────────────────────────
def test_add_book_created(client):
    conn = FakeConn(responses=[{"id": 55}])               # INSERT ... RETURNING id
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/recipes/book", json={"recipe_id": 100})
    assert r.status_code == 201
    assert r.json() == {"id": 55}
    sql, params = conn.executed[0]
    assert "insert into recipebook.bookmark" in sql.lower()
    assert params == (7, 100)                             # user_id는 JWT(7), 바디 아님(A01)


def test_add_duplicate_409(client):
    OV[get_conn] = lambda: FakeConn(raise_exc=UniqueViolation("dup"))
    OV[get_current_user] = lambda: 7
    r = client.post("/api/recipes/book", json={"recipe_id": 100})
    assert r.status_code == 409


def test_add_unknown_recipe_404(client):
    # 없는 recipe_id → FK 위반 → 404
    OV[get_conn] = lambda: FakeConn(raise_exc=ForeignKeyViolation("no recipe"))
    OV[get_current_user] = lambda: 7
    r = client.post("/api/recipes/book", json={"recipe_id": 999999})
    assert r.status_code == 404


def test_add_requires_auth(client):
    assert client.post("/api/recipes/book", json={"recipe_id": 1}).status_code == 401


def test_add_rejects_bad_recipe_id(client):
    # 입력 검증(A05): recipe_id < 1 → 422
    OV[get_current_user] = lambda: 7
    OV[get_conn] = lambda: FakeConn()
    assert client.post("/api/recipes/book", json={"recipe_id": 0}).status_code == 422


# ── #22 DELETE /api/recipes/book/{id} ──────────────────────────────────────
def test_delete_book_204(client):
    conn = FakeConn(responses=[{"id": 5}])                # DELETE ... RETURNING id
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.delete("/api/recipes/book/5")
    assert r.status_code == 204
    assert r.content == b""                               # 204 → 빈 바디
    sql, params = conn.executed[0]
    assert "delete from recipebook.bookmark" in sql.lower()
    assert "user_id = %s" in sql.lower()                  # 소유권 필터
    assert params == (5, 7)                               # (bookmark_id, user_id=JWT)


def test_delete_others_bookmark_404(client):
    # 남의 행 → WHERE id=%s AND user_id=%s 매칭 0 → RETURNING None → 404 (소유권, A01)
    OV[get_conn] = lambda: FakeConn(responses=[])
    OV[get_current_user] = lambda: 7
    r = client.delete("/api/recipes/book/5")
    assert r.status_code == 404


def test_delete_requires_auth(client):
    assert client.delete("/api/recipes/book/5").status_code == 401
