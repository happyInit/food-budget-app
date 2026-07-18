"""라우터 골든 테스트 — 주입 seam으로 실 DB·실 JWT 없이 핸들러를 통째 검증. (account 패턴)
   OV[get_conn] = lambda: FakeConn([...])        → DB 없이 쿼리 결과(dict) 주입
   OV[get_current_user] = lambda: 7              → 인증 통과 가장(소유자 user_id=7)
FakeConn 응답은 dict (풀 row_factory=dict_row와 동일 shape).
무엇을 검증하나: 소유자 스코프(A01)·인증 실패(A07)·status 전이·Pydantic 422(A05)·SQL 매핑.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from psycopg.errors import ForeignKeyViolation

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


def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text


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
    # 실온→냉장(앵커 없음): 냉동 아님 → 소비기한 재계산 없이 storage 만 갱신(단일 update).
    conn = FakeConn(responses=[_item(id=5, storage="FRIDGE")])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.patch("/api/pantry/items/5", json={"storage": "FRIDGE"})
    assert r.status_code == 200
    assert r.json()["storage"] == "FRIDGE"
    assert len(conn.executed) == 1                            # 재계산 미발생 → 단일 update
    sql, params = conn.executed[0]
    assert "update pantry.pantry_item set" in sql
    assert "storage = %s" in sql and "name = %s" not in sql   # 미제공 필드는 SET 에 없음
    assert "where id = %s and user_id = %s" in sql            # A01 소유자 스코프
    assert params == ("FRIDGE", 5, 7)                         # (값…, id, uid)


def test_patch_to_freezer_recomputes_expire_from_shelf_life(client):
    # 냉장→냉동 이동(#3): 앵커 있으면 냉동 shelf_life 로 소비기한 재계산(길어짐).
    moved = _item(id=5, item_id=100, storage="FREEZER", expire_at=date(2026, 7, 20))
    frozen = _item(id=5, item_id=100, storage="FREEZER", expire_at=date.today() + timedelta(days=90))
    conn = FakeConn(responses=[moved, {"days_min": 30, "days_max": 90}, frozen])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.patch("/api/pantry/items/5", json={"storage": "FREEZER"})
    assert r.status_code == 200
    assert len(conn.executed) == 3                            # storage update + shelf_life 조회 + expire 재계산 update
    assert "shelf_life_ref" in conn.executed[1][0]
    assert conn.executed[1][1] == (100, "FREEZER")           # (item_id, 새 storage) 로 조회
    assert (date.today() + timedelta(days=90)) in conn.executed[2][1]   # 냉동 기준 재계산치를 update
    assert r.json()["expire_at"] == (date.today() + timedelta(days=90)).isoformat()


def test_patch_to_freezer_no_anchor_freezes_indefinitely(client):
    # 앵커(item_id) 없는 재료가 냉동으로 → 무기한 동결(expire_at=null). shelf_life 조회 없음.
    moved = _item(id=5, item_id=None, storage="FREEZER", expire_at=date(2026, 8, 1))
    frozen = _item(id=5, item_id=None, storage="FREEZER", expire_at=None)
    conn = FakeConn(responses=[moved, frozen])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.patch("/api/pantry/items/5", json={"storage": "FREEZER"})
    assert r.status_code == 200
    assert len(conn.executed) == 2                            # storage update + expire=null update (조회 없음)
    assert None in conn.executed[1][1]                        # expire_at 을 null 로
    assert r.json()["expire_at"] is None


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


# ── GET /api/pantry/stats (성과지표) ───────────────────────────────────────
def test_stats_counts_by_status_owner_scoped(client):
    conn = FakeConn(responses=[{"active": 5, "consumed": 8, "discarded": 2}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/pantry/stats")
    assert r.status_code == 200
    assert r.json() == {"active": 5, "consumed": 8, "discarded": 2, "saved_rate": 0.8}
    sql, params = conn.executed[0]
    assert "from pantry.pantry_item" in sql
    assert "where user_id = %s" in sql        # A01 소유자 스코프
    assert params[-1] == 7                     # user_id 마지막 바인딩(요청 아님 — JWT)


def test_stats_month_filter_binds_first_of_month(client):
    conn = FakeConn(responses=[{"active": 3, "consumed": 1, "discarded": 0}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/pantry/stats?month=2026-07")
    assert r.status_code == 200
    assert r.json()["saved_rate"] == 1.0                  # 1/(1+0)
    assert date(2026, 7, 1) in conn.executed[0][1]        # closed_at 월 필터 date 바인딩


def test_stats_saved_rate_null_when_nothing_closed(client):
    conn = FakeConn(responses=[{"active": 4, "consumed": 0, "discarded": 0}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/pantry/stats")
    assert r.json()["saved_rate"] is None                 # 분모 0 → 나눗셈 안 함


def test_stats_bad_month_422(client):
    OV[get_current_user] = lambda: 7
    OV[get_conn] = lambda: FakeConn(responses=[])
    assert client.get("/api/pantry/stats?month=2026-13").status_code == 422  # 13월(실월 검증)
    assert client.get("/api/pantry/stats?month=07-2026").status_code == 422  # 형식(pattern)


def test_stats_requires_auth(client):
    assert client.get("/api/pantry/stats").status_code == 401


# ── #12 POST /api/pantry/items ─────────────────────────────────────────────
def test_add_item_stores_explicit_expire_and_owner(client):
    # item_id 미지정 → resolve_item_id(매칭실패=None) 후 INSERT. expire_at 명시라 shelf_life 조회는 없음.
    conn = FakeConn(responses=[{"item_id": None}, CREATED])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/pantry/items", json={
        "name": "두부", "quantity": "1모", "storage": "FRIDGE", "expire_at": "2026-08-01"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == 1 and body["storage"] == "FRIDGE"
    assert body["expire_at"] == "2026-08-01" and body["status"] == "ACTIVE"
    # resolve(이름→item_id) + INSERT 2건. 소유자 user_id=7(요청 바디 아님) 은 INSERT 에.
    assert len(conn.executed) == 2
    sql, params = conn.executed[1]
    assert "insert into pantry.pantry_item" in sql
    assert 7 in params
    assert date(2026, 8, 1) in params


def test_add_item_auto_resolves_item_id_from_name(client):
    # item 4: 표준품목 미지정이라도 이름이 item_master/alias 에 매칭되면 item_id 자동 부착
    # → '뭐 해먹지' 추천(item_id 매칭)에 즉시 반영. expire_at 명시로 shelf_life 조회는 생략.
    conn = FakeConn(responses=[{"item_id": 29}, _item(item_id=29, name="양파")])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/pantry/items", json={
        "name": "양파", "storage": "FRIDGE", "expire_at": "2026-08-01"})
    assert r.status_code == 201
    assert r.json()["item_id"] == 29
    resolve_sql, resolve_params = conn.executed[0]      # 첫 쿼리 = 이름→item_id 해석
    assert "item_master" in resolve_sql and "item_alias" in resolve_sql
    assert "양파" in resolve_params
    ins_sql, ins_params = conn.executed[1]              # INSERT 에 resolve 된 29 가 실림
    assert "insert into pantry.pantry_item" in ins_sql
    assert 29 in ins_params


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


def test_add_item_unknown_item_id_404(client):
    # 없는 item_id(item_master FK) → INSERT 에서 FK 위반 → 404 (recipebook 매핑 역이식).
    # expire_at 명시 → shelf_life 조회 건너뛰고 곧장 INSERT(단일 execute)에서 위반.
    OV[get_conn] = lambda: FakeConn(raise_exc=ForeignKeyViolation("no item_master"))
    OV[get_current_user] = lambda: 7
    r = client.post("/api/pantry/items", json={
        "name": "두부", "storage": "FRIDGE", "item_id": 999999, "expire_at": "2026-08-01"})
    assert r.status_code == 404


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


# ── POST /api/pantry/receipts (OCR 확정) ───────────────────────────────────
def test_confirm_receipt_persists_and_computes_expense(client):
    # 식품(두부, item_id=11, keep) + 비식품(봉투, keep=false). 식비=total−Σ비식품.
    # fetchone 순서: create_ocr_receipt(id) → valid_item_id(11) → create_item(row).
    #   봉투는 item_id=None → valid_item_id 조기반환(쿼리 X), keep=false → pantry 미저장.
    conn = FakeConn(responses=[{"id": 42}, {"item_id": 11}, CREATED])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/pantry/receipts", json={
        "store": "마켓컬리", "purchased_at": "2026-07-13T18:42:00", "total_amount": 10000,
        "items": [
            {"name": "두부", "item_id": 11, "quantity": "1모", "price": 8800,
             "category": "식재료", "storage": "FRIDGE", "expire_at": "2026-08-01", "keep": True},
            {"name": "종량제봉투", "price": 1200, "is_food": False,
             "category": "비식품", "keep": False},
        ],
    })
    assert r.status_code == 201
    body = r.json()
    assert body == {
        "receipt_id": 42, "added_count": 1, "expense_amount": 8800,
        "expense_basis": "total_anchor", "needs_expense_review": False,   # 라인합 10000 == total
    }
    # A01: ocr_receipt 헤더가 JWT user_id(7)로 저장(바디 user_id 불신)
    sql0, params0 = conn.executed[0]
    assert "insert into pantry.ocr_receipt" in sql0 and params0[0] == 7
    # pantry_item 은 source='OCR' 로 저장(식품만)
    pantry_ins = [(s, p) for s, p in conn.executed if "insert into pantry.pantry_item" in s]
    assert len(pantry_ins) == 1 and pantry_ins[0][1][-1] == "OCR"


def test_confirm_receipt_fallback_when_no_total(client):
    # total 없음 → 식품 양수합 fallback + needs_expense_review=True.
    # fetchone 순서: create_ocr_receipt(id) → resolve_item_id(99) → lookup_shelf_life(None) → create_item(row).
    conn = FakeConn(responses=[{"id": 43}, {"item_id": 99}, None, CREATED])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/pantry/receipts", json={
        "items": [
            {"name": "사과", "price": 5000, "category": "식재료", "storage": "FRIDGE", "keep": True},
        ],
    })
    assert r.status_code == 201
    body = r.json()
    assert body["expense_amount"] == 5000
    assert body["expense_basis"] == "line_sum_fallback"
    assert body["needs_expense_review"] is True
    assert body["added_count"] == 1


def test_confirm_receipt_requires_auth(client):
    r = client.post("/api/pantry/receipts", json={"items": []})
    assert r.status_code == 401
