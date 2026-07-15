"""라우터 골든 테스트 — 주입 seam으로 실 DB·실 JWT·크로스서비스 없이 핸들러를 통째 검증.
override 패턴(account 복제):
   OV[get_conn] = lambda: FakeConn([...])        DB 없이 쿼리 결과 주입
   OV[get_current_user] = lambda: 7              인증 통과 가장(미오버라이드 시 실제 401)
   OV[get_budget_provider/get_pantry_provider]   크로스서비스 seam fake 주입
검증 포인트: (a) SQL 매핑·정상응답 (b) 에러코드(400/404/422) (c) 인증없이 401
           (d) 소유권(WHERE user_id 파라미터·남의 행 None→404).
"""
from __future__ import annotations

from datetime import date

import app.main as main_mod
from app.context import (
    get_budget_provider, get_conn, get_current_user, get_pantry_provider,
)
from tests.fakes import (
    FakeBudgetProvider, FakeConn, FakePantryProvider, stock,
)

OV = main_mod.app.dependency_overrides


# ── #34 POST cart/items ─────────────────────────────────────────────────────
def test_add_cart_item_created(client):
    conn = FakeConn(responses=[{"id": 101}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/mealplan/cart/items",
                    json={"name": "대파", "item_id": 10, "qty": 2, "quantity": "1단"})
    assert r.status_code == 201
    assert r.json() == {"id": 101}
    sql, params = conn.executed[0]
    assert "insert into mealplan.cart_item" in sql
    assert params[0] == 7                       # user_id는 JWT에서(바디 아님, A01)
    assert 10 in params and 2 in params


def test_add_cart_item_rejects_bad_qty(client):
    OV[get_conn] = lambda: FakeConn(responses=[{"id": 1}])
    OV[get_current_user] = lambda: 7
    r = client.post("/api/mealplan/cart/items", json={"name": "대파", "qty": 0})
    assert r.status_code == 422                  # qty ge=1 (A05 입력검증)


def test_add_cart_item_bad_reference_400(client):
    # 없는 recipe/item/product id → public FK 위반 → 500 아니라 400 매핑
    from psycopg.errors import ForeignKeyViolation
    OV[get_conn] = lambda: FakeConn(raise_exc=ForeignKeyViolation("fk"))
    OV[get_current_user] = lambda: 7
    r = client.post("/api/mealplan/cart/items", json={"name": "x", "recipe_id": 999999})
    assert r.status_code == 400


# ── #33 GET cart (+ budget seam) ────────────────────────────────────────────
def test_get_cart_maps_items_and_budget(client):
    rows = [
        {"id": 1, "name": "대파", "qty": 2, "quantity": "1단", "item_id": 10,
         "lowest_krw_per_100g": 300, "source": "kurly"},
        {"id": 2, "name": "두부", "qty": 1, "quantity": None, "item_id": 20,
         "lowest_krw_per_100g": 150, "source": "oasis"},
        {"id": 3, "name": "미상", "qty": 5, "quantity": None, "item_id": None,
         "lowest_krw_per_100g": None, "source": None},
    ]
    conn = FakeConn(responses=rows)
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    OV[get_budget_provider] = lambda: FakeBudgetProvider(amount=100000)
    r = client.get("/api/mealplan/cart")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3
    assert body["items"][0] == {"id": 1, "name": "대파", "qty": 2, "quantity": "1단",
                                "item_id": 10, "lowest_krw_per_100g": 300, "source": "kurly"}
    assert body["items"][2]["lowest_krw_per_100g"] is None      # 가격 미상 통과
    assert body["subtotal"] == 300 * 2 + 150 * 1                # 미상행 제외 = 750
    assert body["budget"] == 100000
    assert body["remaining"] == 100000 - 750
    assert conn.executed[0][1] == (7,)                          # WHERE user_id = 7 (소유권)


def test_get_cart_budget_null_when_seam_unavailable(client):
    # budget provider 미오버라이드 → 기본 Http 어댑터(미배선) → ProviderUnavailable → null degrade
    OV[get_conn] = lambda: FakeConn(responses=[])
    OV[get_current_user] = lambda: 7
    r = client.get("/api/mealplan/cart")
    assert r.status_code == 200
    assert r.json() == {"items": [], "subtotal": 0, "budget": None, "remaining": None}


def test_get_cart_requires_auth(client):
    # get_current_user 미오버라이드 → Bearer 없음 → 401 (conn 의존성은 도달 전)
    assert client.get("/api/mealplan/cart").status_code == 401


# ── #35 DELETE cart/items/{id} (소유권) ─────────────────────────────────────
def test_delete_cart_item_no_content(client):
    conn = FakeConn(responses=[{"id": 5}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.delete("/api/mealplan/cart/items/5")
    assert r.status_code == 204
    assert conn.executed[0][1] == (5, 7)         # (id, user_id) — 소유권 바인딩


def test_delete_others_cart_item_404(client):
    # 남의 행 → WHERE id AND user_id 로 아무 행도 안 지워짐 → None → 404 (A01)
    conn = FakeConn(responses=[])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.delete("/api/mealplan/cart/items/999")
    assert r.status_code == 404
    assert conn.executed[0][1] == (999, 7)       # user_id 가 쿼리에 실렸는지 확인


# ── #36 POST cart/checkout ──────────────────────────────────────────────────
def test_checkout_creates_expense_and_clears(client):
    cart_rows = [
        {"id": 1, "name": "대파", "qty": 2, "quantity": None, "item_id": 10,
         "lowest_krw_per_100g": 300, "source": "kurly"},
        {"id": 2, "name": "두부", "qty": 1, "quantity": None, "item_id": 20,
         "lowest_krw_per_100g": 150, "source": "oasis"},
    ]
    # 다중 문(같은 conn): get_cart(fetchall) → insert_expense(fetchone) → clear_cart(execute)
    conn = FakeConn(results=[cart_rows, [{"id": 555}]])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/mealplan/cart/checkout")
    assert r.status_code == 200
    assert r.json() == {"order": {"expense_id": 555, "amount": 750}}
    # 지출 insert 에 합계·user_id 가 실렸는지 + 마지막에 cart 비우기(WHERE user_id)
    assert any("insert into mealplan.expense" in s for s, _ in conn.executed)
    assert conn.executed[-1][0].startswith("delete from mealplan.cart_item where user_id")
    assert conn.executed[-1][1] == (7,)


def test_checkout_empty_cart_400(client):
    OV[get_conn] = lambda: FakeConn(results=[[]])
    OV[get_current_user] = lambda: 7
    assert client.post("/api/mealplan/cart/checkout").status_code == 400


# ── #39 POST expenses ───────────────────────────────────────────────────────
def test_add_expense_created(client):
    conn = FakeConn(responses=[{"id": 77}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/expenses",
                    json={"amount": 12000, "category": "DINING", "spent_on": "2026-07-13",
                          "memo": "점심", "source": "MANUAL"})
    assert r.status_code == 201
    assert r.json() == {"id": 77}
    assert conn.executed[0][1][0] == 7           # user_id = JWT


def test_add_expense_rejects_bad_category(client):
    OV[get_conn] = lambda: FakeConn(responses=[{"id": 1}])
    OV[get_current_user] = lambda: 7
    r = client.post("/api/expenses",
                    json={"amount": 1, "category": "HACK", "spent_on": "2026-07-13"})
    assert r.status_code == 422                   # Literal enum 검증 (A05)


# ── #38 GET expenses/calendar ───────────────────────────────────────────────
def test_calendar_groups_by_day(client):
    rows = [{"spent_on": date(2026, 7, 3), "amount": 12000},
            {"spent_on": date(2026, 7, 5), "amount": 3000}]
    conn = FakeConn(responses=rows)
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/expenses/calendar?month=2026-07")
    assert r.status_code == 200
    assert r.json() == {"days": [{"date": "2026-07-03", "amount": 12000},
                                 {"date": "2026-07-05", "amount": 3000}]}
    assert conn.executed[0][1] == (7, date(2026, 7, 1))   # user_id + month 1일 date 바인딩


def test_calendar_bad_month_422(client):
    OV[get_conn] = lambda: FakeConn(responses=[])
    OV[get_current_user] = lambda: 7
    assert client.get("/api/expenses/calendar?month=2026-13").status_code == 422  # 13월
    assert client.get("/api/expenses/calendar?month=07-2026").status_code == 422  # 형식


# ── #40 GET expenses/summary (spent 실 + seam) ──────────────────────────────
def test_summary_spent_real_and_seams(client):
    OV[get_conn] = lambda: FakeConn(responses=[{"spent": 50000}])
    OV[get_current_user] = lambda: 7
    OV[get_budget_provider] = lambda: FakeBudgetProvider(amount=300000)
    OV[get_pantry_provider] = lambda: FakePantryProvider(saved=4)
    r = client.get("/api/expenses/summary?month=2026-07")
    assert r.status_code == 200
    assert r.json() == {"spent": 50000, "budget": 300000,
                        "remain": 250000, "saved_ingredients": 4}


def test_summary_seams_null_when_unavailable(client):
    # budget·pantry seam 미가용 → spent만 실, 나머지 null degrade
    OV[get_conn] = lambda: FakeConn(responses=[{"spent": 50000}])
    OV[get_current_user] = lambda: 7
    OV[get_budget_provider] = lambda: FakeBudgetProvider(unavailable=True)
    OV[get_pantry_provider] = lambda: FakePantryProvider(unavailable=True)
    r = client.get("/api/expenses/summary?month=2026-07")
    assert r.json() == {"spent": 50000, "budget": None,
                        "remain": None, "saved_ingredients": None}


# ── #32 POST mealplan/recommend (pantry seam + 순수 랭킹) ────────────────────
def test_recommend_ranks_with_pantry(client):
    # 재고 10(임박)·20 보유. 후보: 레시피7(10,20 전부보유)·9(10,99 절반).
    cand_rows = [
        {"recipe_id": 7, "recipe_name": "두부김치", "item_id": 10, "ing_cost": 300},
        {"recipe_id": 7, "recipe_name": "두부김치", "item_id": 20, "ing_cost": 150},
        {"recipe_id": 9, "recipe_name": "파전", "item_id": 10, "ing_cost": 300},
        {"recipe_id": 9, "recipe_name": "파전", "item_id": 99, "ing_cost": 500},
    ]
    OV[get_conn] = lambda: FakeConn(responses=cand_rows)
    OV[get_current_user] = lambda: 7
    OV[get_pantry_provider] = lambda: FakePantryProvider(
        stock=[stock(10, expiring=True), stock(20)])
    r = client.post("/api/mealplan/recommend", json={"budget": 100000})
    assert r.status_code == 200
    body = r.json()
    assert body["note"] is None
    ids = [x["recipe_id"] for x in body["recommendations"]]
    assert ids == [7, 9]                          # 커버리지 1.0 인 7 이 먼저
    assert body["recommendations"][0]["coverage"] == 1.0
    assert body["recommendations"][0]["est_cost"] == 450
    assert body["recommendations"][0]["expiring_used"] == 1   # 임박재료 10 사용


def test_recommend_degraded_when_pantry_unavailable(client):
    OV[get_conn] = lambda: FakeConn()             # 도달 안 함(도달 전 degrade)
    OV[get_current_user] = lambda: 7
    OV[get_pantry_provider] = lambda: FakePantryProvider(unavailable=True)
    r = client.post("/api/mealplan/recommend", json={})
    assert r.status_code == 200
    assert r.json()["recommendations"] == []
    assert "unavailable" in r.json()["note"]


def test_recommend_empty_pantry_note(client):
    OV[get_conn] = lambda: FakeConn()
    OV[get_current_user] = lambda: 7
    OV[get_pantry_provider] = lambda: FakePantryProvider(stock=[])
    r = client.post("/api/mealplan/recommend", json={})
    assert r.status_code == 200
    assert r.json()["recommendations"] == []
    assert r.json()["note"] is not None


def test_recommend_requires_auth(client):
    assert client.post("/api/mealplan/recommend", json={}).status_code == 401
