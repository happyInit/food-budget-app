"""user_recipe(#24 수동 등록 + 공유) 라우터 골든 테스트 — 주입 seam(FakeConn) 으로 DB·JWT 없이 검증.
커버: 생성·목록·상세·삭제·공유·공개뷰 / 소유권(A01) / 입력검증(A05) / 인증(A07)."""
from __future__ import annotations

import json

import app.main as main_mod
from app.context import get_conn, get_current_user
from tests.fakes import FakeConn

OV = main_mod.app.dependency_overrides


# ── POST /api/recipes/mine (생성) ──────────────────────────────────────────
def test_create_user_recipe(client):
    conn = FakeConn(responses=[{"id": 42}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/recipes/mine", json={
        "title": "우리집 김치찌개",
        "ingredients": [{"name": "김치", "quantity": "1/2포기"}, {"name": "돼지고기"}],
        "steps": ["김치를 볶는다", "물을 붓고 끓인다"],
    })
    assert r.status_code == 201
    assert r.json() == {"id": 42}
    sql, params = conn.executed[0]
    assert "insert into recipebook.user_recipe" in sql.lower()
    assert "'manual'" in sql.lower()                 # origin은 서버 고정(바디 신뢰 안 함)
    assert params[0] == 7 and params[1] == "우리집 김치찌개"   # user_id는 JWT(7), 바디 아님(A01)
    # jsonb 는 json.dumps 로 직렬화되어 바인딩(A05: 문자열 결합 아님)
    assert json.loads(params[2]) == [{"name": "김치", "quantity": "1/2포기"},
                                     {"name": "돼지고기", "quantity": None}]
    assert json.loads(params[3]) == ["김치를 볶는다", "물을 붓고 끓인다"]


def test_create_requires_auth(client):
    assert client.post("/api/recipes/mine", json={"title": "x"}).status_code == 401


def test_create_rejects_empty_title(client):        # A05 입력검증
    OV[get_current_user] = lambda: 7
    OV[get_conn] = lambda: FakeConn()
    assert client.post("/api/recipes/mine", json={"title": ""}).status_code == 422


def test_create_rejects_too_many_steps(client):     # A05 상한(100)
    OV[get_current_user] = lambda: 7
    OV[get_conn] = lambda: FakeConn()
    r = client.post("/api/recipes/mine", json={"title": "t", "steps": ["s"] * 101})
    assert r.status_code == 422


# ── GET /api/recipes/mine (목록) ───────────────────────────────────────────
def test_list_mine_owner_scoped(client):
    rows = [{"id": 2, "title": "된장찌개", "image_url": None,
             "is_public": False, "created_at": "2026-07-16T10:00:00+00:00"}]
    conn = FakeConn(responses=rows)
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/recipes/mine")
    assert r.status_code == 200
    assert r.json()["recipes"][0]["title"] == "된장찌개"
    sql, params = conn.executed[0]
    assert "where user_id = %s" in sql.lower()       # 소유권(A01)
    assert params == (7,)


# ── GET /api/recipes/mine/{id} (상세) ──────────────────────────────────────
def test_get_mine_parses_jsonb(client):
    row = {"id": 5, "title": "카레", "origin": "MANUAL",
           "ingredients": [{"name": "감자", "quantity": "2개"}], "steps": ["끓인다"],
           "image_url": None, "source_url": None, "is_public": False,
           "share_token": None, "created_at": "2026-07-16T10:00:00+00:00"}
    # 상세 서빙은 재료 이름→item_id 매칭(enrich)을 태움 — 미매칭(item_id None)이면 파생값 전부 None.
    conn = FakeConn(responses=[row, {"name": "감자", "item_id": None}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/recipes/mine/5")
    assert r.status_code == 200
    body = r.json()
    assert body["ingredients"][0]["name"] == "감자"
    assert body["ingredients"][0]["lowest_krw_per_100g"] is None   # 미매칭 → 파생값 None
    assert body["steps"] == ["끓인다"]
    sql, params = conn.executed[0]
    assert "id = %s and user_id = %s" in sql.lower()  # 소유권
    assert params == (5, 7)


def test_get_mine_enriches_matched_item_id(client):
    # 매칭되는 재료(두부→item_id 100)면 item_id 가 채워진다(그 뒤 가격·영양 조인 경로로 이어짐).
    # FakeConn.fetchall 은 남은 큐를 통째 비워 스텝별 응답 분리가 어려우므로, 여기선 매칭 경로가
    # 실제로 도는지(item_id 채워짐)까지 검증 — 가격·영양 실조인은 통합/실DB 테스트 영역.
    row = {"id": 6, "title": "두부조림", "origin": "MANUAL",
           "ingredients": [{"name": "두부", "quantity": "1모"}], "steps": ["조린다"],
           "image_url": None, "source_url": None, "is_public": False,
           "share_token": None, "created_at": "2026-07-16T10:00:00+00:00"}
    conn = FakeConn(responses=[row, {"name": "두부", "item_id": 100}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/recipes/mine/6")
    assert r.status_code == 200
    assert r.json()["ingredients"][0]["item_id"] == 100


def test_get_others_recipe_404(client):              # A01: 남의 것 → 404
    OV[get_conn] = lambda: FakeConn(responses=[])
    OV[get_current_user] = lambda: 7
    assert client.get("/api/recipes/mine/5").status_code == 404


# ── DELETE /api/recipes/mine/{id} ──────────────────────────────────────────
def test_delete_mine_204(client):
    conn = FakeConn(responses=[{"id": 5}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.delete("/api/recipes/mine/5")
    assert r.status_code == 204
    sql, params = conn.executed[0]
    assert "delete from recipebook.user_recipe" in sql.lower()
    assert params == (5, 7)


def test_delete_others_recipe_404(client):
    OV[get_conn] = lambda: FakeConn(responses=[])
    OV[get_current_user] = lambda: 7
    assert client.delete("/api/recipes/mine/5").status_code == 404


# ── POST /api/recipes/mine/{id}/share (공유) ───────────────────────────────
def test_share_generates_token_and_public(client):
    conn = FakeConn(responses=[{"share_token": "tok_abc123", "is_public": True}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/recipes/mine/5/share")
    assert r.status_code == 200
    assert r.json() == {"share_token": "tok_abc123", "is_public": True}
    sql, params = conn.executed[0]
    assert "set is_public = true" in sql.lower()
    assert "coalesce(share_token" in sql.lower()      # 기존 토큰 유지(링크 안정)
    assert "id = %s and user_id = %s" in sql.lower()  # 소유자만 공유 설정(A01)
    assert params[1:] == (5, 7)                        # params[0]=새 토큰(랜덤)


def test_share_others_recipe_404(client):
    OV[get_conn] = lambda: FakeConn(responses=[])
    OV[get_current_user] = lambda: 7
    assert client.post("/api/recipes/mine/5/share").status_code == 404


def test_unshare_204(client):
    conn = FakeConn(responses=[{"id": 5}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.delete("/api/recipes/mine/5/share")
    assert r.status_code == 204
    assert "set is_public = false" in conn.executed[0][0].lower()


# ── POST /api/recipes/mine/{id}/publish (공개 카탈로그 발행) ────────────────
def test_publish_snapshots_and_public(client):
    # publish 3스텝: (1)소유자조회→token (2)user_recipe 공개 (3)shared_recipe 업서트 returning
    conn = FakeConn(responses=[{"token": "tok_pub1"}, {"share_token": "tok_pub1"}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/recipes/mine/5/publish")
    assert r.status_code == 200
    assert r.json() == {"share_token": "tok_pub1", "is_public": True}
    assert len(conn.executed) == 3                                   # select → update → insert
    assert "id = %s and user_id = %s" in conn.executed[0][0].lower()  # 소유자 스코프(A01)
    assert "set is_public = true" in conn.executed[1][0].lower()
    ins = conn.executed[2][0].lower()
    assert "insert into recipebook.shared_recipe" in ins
    assert "on conflict (user_recipe_id)" in ins                     # 재발행 = 업서트


def test_publish_others_recipe_404(client):
    OV[get_conn] = lambda: FakeConn(responses=[])   # 소유자 조회 0건 → 404
    OV[get_current_user] = lambda: 7
    assert client.post("/api/recipes/mine/5/publish").status_code == 404


def test_publish_requires_auth(client):
    assert client.post("/api/recipes/mine/5/publish").status_code == 401


def test_unpublish_204(client):
    conn = FakeConn(responses=[{"id": 5}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.delete("/api/recipes/mine/5/publish")
    assert r.status_code == 204
    assert "set is_public = false" in conn.executed[0][0].lower()
    assert "delete from recipebook.shared_recipe" in conn.executed[1][0].lower()


def test_unpublish_others_recipe_404(client):
    OV[get_conn] = lambda: FakeConn(responses=[])
    OV[get_current_user] = lambda: 7
    assert client.delete("/api/recipes/mine/5/publish").status_code == 404


# ── GET /api/recipes/shared (공개 발행 목록, 비인증) ───────────────────────
def test_list_shared_no_auth(client):
    rows = [{"id": 3, "title": "우리집 김치찌개", "image_url": None, "origin": "MANUAL",
             "share_token": "tok_pub1", "published_at": "2026-07-16T10:00:00+00:00"}]
    conn = FakeConn(responses=rows)
    OV[get_conn] = lambda: conn
    # get_current_user 미오버라이드 — 공개 목록은 비인증
    r = client.get("/api/recipes/shared?q=김치")
    assert r.status_code == 200
    card = r.json()["recipes"][0]
    assert card["title"] == "우리집 김치찌개" and card["share_token"] == "tok_pub1"
    assert "user_id" not in card                       # 작성자 식별정보 미노출
    sql, _ = conn.executed[0]
    assert "from recipebook.shared_recipe" in sql.lower()
    assert "ilike" in sql.lower()                       # q 검색


# ── GET /api/recipes/shared/{token} (공개 뷰, 비인증) ──────────────────────
def test_shared_view_no_auth(client):
    row = {"title": "공유된 레시피", "ingredients": [{"name": "당근"}],
           "steps": ["썬다"], "image_url": None}
    # 공개 뷰도 상세 서빙이라 enrich(이름 매칭)를 태움 — 미매칭 응답 주입.
    conn = FakeConn(responses=[row, {"name": "당근", "item_id": None}])
    OV[get_conn] = lambda: conn
    # get_current_user 미오버라이드 — 공개 뷰는 인증 불요
    r = client.get("/api/recipes/shared/tok_abc123")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "공유된 레시피"
    assert "user_id" not in body                       # 작성자 식별정보 미노출
    sql, params = conn.executed[0]
    assert "is_public = true" in sql.lower()            # 공개된 것만
    assert params == ("tok_abc123",)


def test_shared_view_missing_404(client):
    OV[get_conn] = lambda: FakeConn(responses=[])
    assert client.get("/api/recipes/shared/nope").status_code == 404
