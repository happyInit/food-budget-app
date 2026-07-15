"""라우터 골든 테스트 — 주입 seam으로 실 DB·실 JWT 없이 핸들러를 통째 검증. (account 패턴)
   OV[get_conn] = lambda: FakeConn([...])        → DB 없이 쿼리 결과(dict) 주입
   OV[get_current_user] = lambda: 7              → 인증 통과 가장(소유자 user_id=7)
FakeConn 응답은 dict (풀 row_factory=dict_row와 동일 shape).
무엇을 검증하나: 소유자 스코프(A01)·인증 실패(A07)·status 전이·Pydantic 422(A05)·SQL 매핑.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import app.main as main_mod
from app.context import get_conn, get_current_user
from tests.fakes import FakeConn

OV = main_mod.app.dependency_overrides

# INSERT ... RETURNING 이 돌려주는 행 shape(풀 dict_row) — PantryItemOut 컬럼과 동일.
CREATED = {
    "id": 1, "item_id": None, "name": "두부", "quantity": "1모",
    "storage": "FRIDGE", "expire_at": date(2026, 8, 1), "source": "MANUAL",
    "status": "ACTIVE", "created_at": datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc),
    "closed_at": None,
}


def _item(**over):
    """CREATED 기반 재고 행 헬퍼(dict_row shape)."""
    base = dict(CREATED)
    base.update(over)
    return base


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "pantry"}


# ── #11 GET /api/pantry/items ──────────────────────────────────────────────
def test_list_items_owner_scoped(client):
    conn = FakeConn(responses=[_item(id=1, name="우유"), _item(id=2, name="계란", expire_at=None)])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/pantry/items")
    assert r.status_code == 200
    assert [i["id"] for i in r.json()] == [1, 2]
    sql, params = conn.executed[0]
    assert "from pantry.pantry_item" in sql
    assert "user_id = %s" in sql and "status = 'ACTIVE'" in sql   # A01 소유자 + ACTIVE만
    assert params == (7,)                                         # JWT uid 로만 스코프


def test_list_requires_auth(client):
    assert client.get("/api/pantry/items").status_code == 401


# ── #15 GET /api/pantry/expiring ───────────────────────────────────────────
def test_expiring_owner_scoped_within_days(client):
    conn = FakeConn(responses=[_item(id=1, name="우유", expire_at=date(2026, 7, 16))])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/pantry/expiring?within_days=5")
    assert r.status_code == 200
    assert [i["id"] for i in r.json()] == [1]
    sql, params = conn.executed[0]
    assert "from pantry.pantry_item" in sql
    assert "user_id = %s" in sql and "status = 'ACTIVE'" in sql
    assert "expire_at is not null" in sql and "expire_at <= current_date + %s" in sql
    assert params == (7, 5)                       # (uid, within_days)


def test_expiring_defaults_to_3_days(client):
    conn = FakeConn(responses=[])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/pantry/expiring")
    assert r.status_code == 200
    assert conn.executed[0][1] == (7, 3)          # 기본 within_days=3


def test_expiring_rejects_out_of_range(client):
    OV[get_current_user] = lambda: 7
    OV[get_conn] = lambda: FakeConn(responses=[])
    assert client.get("/api/pantry/expiring?within_days=999").status_code == 422  # 상한 30 (A05)


def test_expiring_requires_auth(client):
    assert client.get("/api/pantry/expiring").status_code == 401


# ── #13 PATCH /api/pantry/items/{id} ───────────────────────────────────────
def test_patch_updates_only_provided_fields_owner_scoped(client):
    conn = FakeConn(responses=[_item(id=5, storage="FREEZER")])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.patch("/api/pantry/items/5", json={"storage": "FREEZER"})
    assert r.status_code == 200
    assert r.json()["storage"] == "FREEZER"
    sql, params = conn.executed[0]
    assert "update pantry.pantry_item set" in sql
    assert "storage = %s" in sql and "name = %s" not in sql   # 미제공 필드는 SET 에 없음
    assert "where id = %s and user_id = %s" in sql            # A01 소유자 스코프
    assert params == ("FREEZER", 5, 7)                        # (값…, id, uid)


def test_patch_consumed_sets_closed_at(client):
    conn = FakeConn(responses=[_item(id=5, status="CONSUMED")])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.patch("/api/pantry/items/5", json={"status": "CONSUMED"})
    assert r.status_code == 200
    sql, params = conn.executed[0]
    assert "status = %s" in sql and "closed_at = now()" in sql  # 소모/폐기 → 이력 기록(성과지표)
    assert params == ("CONSUMED", 5, 7)


def test_patch_active_clears_closed_at(client):
    conn = FakeConn(responses=[_item(id=5, status="ACTIVE")])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.patch("/api/pantry/items/5", json={"status": "ACTIVE"})
    assert r.status_code == 200
    assert "closed_at = null" in conn.executed[0][0]           # 되돌리면 이력 해제


def test_patch_other_user_item_404(client):
    conn = FakeConn(responses=[])              # 0행 갱신 = 다른 유저 or 없음
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.patch("/api/pantry/items/5", json={"storage": "FRIDGE"})
    assert r.status_code == 404                # A01: 남의 항목 수정 불가(존재도 노출 안 함)


def test_patch_empty_body_422(client):
    OV[get_current_user] = lambda: 7
    OV[get_conn] = lambda: FakeConn(responses=[])
    assert client.patch("/api/pantry/items/5", json={}).status_code == 422  # 수정할 필드 없음


def test_patch_requires_auth(client):
    assert client.patch("/api/pantry/items/5", json={"storage": "FRIDGE"}).status_code == 401


# ── #14 DELETE /api/pantry/items/{id} ──────────────────────────────────────
def test_delete_item_owner_scoped_204(client):
    conn = FakeConn(responses=[{"id": 5}])     # DELETE ... RETURNING id
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.delete("/api/pantry/items/5")
    assert r.status_code == 204
    sql, params = conn.executed[0]
    assert "delete from pantry.pantry_item" in sql
    assert "where id = %s and user_id = %s" in sql   # A01 소유자 스코프
    assert params == (5, 7)


def test_delete_other_user_item_404(client):
    conn = FakeConn(responses=[])              # 0행 삭제 = 다른 유저 or 없음
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.delete("/api/pantry/items/5")
    assert r.status_code == 404                # A01: 남의 항목 삭제 불가(존재도 노출 안 함)


def test_delete_requires_auth(client):
    assert client.delete("/api/pantry/items/5").status_code == 401


# ── #12 POST /api/pantry/items ─────────────────────────────────────────────
def test_add_item_stores_explicit_expire_and_owner(client):
    conn = FakeConn(responses=[CREATED])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/pantry/items", json={
        "name": "두부", "quantity": "1모", "storage": "FRIDGE", "expire_at": "2026-08-01"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == 1 and body["storage"] == "FRIDGE"
    assert body["expire_at"] == "2026-08-01" and body["status"] == "ACTIVE"
    # A01: expire_at 명시 → shelf_life 조회 없이 INSERT 1건, 소유자 user_id=7(요청 바디 아님).
    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    assert "insert into pantry.pantry_item" in sql
    assert 7 in params
    assert date(2026, 8, 1) in params


def test_add_item_estimates_expire_from_shelf_life(client):
    # expire_at 미입력 + item_id 있음 → shelf_life 조회(3~7일) → 담은날 + days_max(7) 를 INSERT.
    conn = FakeConn(responses=[{"days_min": 3, "days_max": 7}, CREATED])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/pantry/items", json={"name": "두부", "storage": "FRIDGE", "item_id": 100})
    assert r.status_code == 201
    assert len(conn.executed) == 2                          # shelf_life 조회 + INSERT
    assert "shelf_life_ref" in conn.executed[0][0]
    assert conn.executed[0][1] == (100, "FRIDGE")           # (item_id, storage) 로 조회
    insert_sql, insert_params = conn.executed[1]
    assert "insert into pantry.pantry_item" in insert_sql
    assert date.today() + timedelta(days=7) in insert_params  # days_max 추정치가 INSERT 로


def test_add_item_leaves_expire_null_when_no_shelf_life_match(client):
    # item_id 있으나 shelf_life 미앵커(조회 None) → expire_at 은 null 유지(유저입력 대기).
    conn = FakeConn(responses=[None, CREATED])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/pantry/items", json={"name": "깻잎", "storage": "FRIDGE", "item_id": 999})
    assert r.status_code == 201
    assert len(conn.executed) == 2
    insert_params = conn.executed[1][1]
    assert not any(isinstance(p, date) for p in insert_params)  # 어떤 date 도 INSERT 안 됨 → expire_at null


def test_add_item_rejects_bad_storage(client):
    OV[get_current_user] = lambda: 7
    OV[get_conn] = lambda: FakeConn(responses=[CREATED])
    r = client.post("/api/pantry/items", json={"name": "두부", "storage": "PANTRY"})
    assert r.status_code == 422                              # storage enum 위반(A05)


def test_add_item_rejects_empty_name(client):
    OV[get_current_user] = lambda: 7
    OV[get_conn] = lambda: FakeConn(responses=[CREATED])
    r = client.post("/api/pantry/items", json={"name": "", "storage": "FRIDGE"})
    assert r.status_code == 422                              # name min_length=1 (A05)


def test_add_item_requires_auth(client):
    # get_current_user 미오버라이드 + Bearer 없음 → 401 (A01/A07). 바디 유효하므로 인증만 실패.
    r = client.post("/api/pantry/items", json={"name": "두부", "storage": "FRIDGE"})
    assert r.status_code == 401
