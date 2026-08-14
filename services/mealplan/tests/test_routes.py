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
    get_budget_provider, get_conn, get_conn_opener, get_current_user, get_exclusion_provider,
    get_pantry_provider,
)
from tests.fakes import (
    FakeBudgetProvider, FakeConn, FakeExclusionProvider, FakePantryProvider, opener, stock,
)

OV = main_mod.app.dependency_overrides


def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text


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


def test_add_cart_item_merges_same_item(client):
    """#614 같은 품목은 새 행 대신 qty 합산 — arbiter = 부분 유니크 ux_cart_item_user_item.

    유저는 레시피를 오가며 담아 프론트가 "이미 담겼는지"를 모른다 → 합산은 서버 몫.
    returning id 가 **기존 행 id** 를 돌려주는 것도 계약(프론트는 201 만 본다).
    """
    conn = FakeConn(responses=[{"id": 101}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/mealplan/cart/items",
                    json={"name": "대파", "item_id": 10, "qty": 1, "quantity": "1단"})
    assert r.status_code == 201
    assert r.json() == {"id": 101}
    sql, _ = conn.executed[0]
    assert "on conflict (user_id, item_id) where item_id is not null" in sql
    assert "do update set qty = cart_item.qty + excluded.qty" in sql
    # 합쳐도 출처(recipe_id)·표시수량(quantity)은 첫 행 유지 — qty 말고 아무것도 안 건드린다
    assert "recipe_id = excluded" not in sql and "quantity = excluded" not in sql
    assert "name = excluded" not in sql


def test_add_cart_item_without_item_id_is_not_merged(client):
    """item_id 미매칭(null)은 이름만으로 동일 품목이라 단정 못 한다 → 부분 인덱스 밖 = 그대로 새 행."""
    conn = FakeConn(responses=[{"id": 102}])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.post("/api/mealplan/cart/items", json={"name": "손질된 무언가", "qty": 1})
    assert r.status_code == 201
    sql, params = conn.executed[0]
    assert params[3] is None                     # item_id — null 이면 충돌 대상이 아니다
    assert "where item_id is not null" in sql    # 부분 인덱스 술어(= null 행은 안 합쳐짐)


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
    OV[get_conn_opener] = lambda: opener(conn)
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
    OV[get_conn_opener] = lambda: opener(FakeConn(responses=[]))
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
    OV[get_conn_opener] = lambda: opener(FakeConn(responses=[{"spent": 50000}]))
    OV[get_current_user] = lambda: 7
    OV[get_budget_provider] = lambda: FakeBudgetProvider(amount=300000)
    OV[get_pantry_provider] = lambda: FakePantryProvider(saved=4)
    r = client.get("/api/expenses/summary?month=2026-07")
    assert r.status_code == 200
    assert r.json() == {"spent": 50000, "budget": 300000,
                        "remaining": 250000, "saved_ingredients": 4}


def test_summary_seams_null_when_unavailable(client):
    # budget·pantry seam 미가용 → spent만 실, 나머지 null degrade
    OV[get_conn_opener] = lambda: opener(FakeConn(responses=[{"spent": 50000}]))
    OV[get_current_user] = lambda: 7
    OV[get_budget_provider] = lambda: FakeBudgetProvider(unavailable=True)
    OV[get_pantry_provider] = lambda: FakePantryProvider(unavailable=True)
    r = client.get("/api/expenses/summary?month=2026-07")
    assert r.json() == {"spent": 50000, "budget": None,
                        "remaining": None, "saved_ingredients": None}


# ── GET expenses/breakdown (성과보기 '식비 구성') ────────────────────────────
def test_breakdown_sums_by_category_and_fills_zeros(client):
    rows = [{"category": "GROCERY", "amount": 68400}, {"category": "DINING", "amount": 35000}]
    conn = FakeConn(responses=rows)
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/expenses/breakdown?month=2026-07")
    assert r.status_code == 200
    body = r.json()
    assert body["month"] == "2026-07"
    assert body["total"] == 103400
    cats = {c["category"]: c for c in body["categories"]}
    assert set(cats) == {"GROCERY", "DINING", "DELIVERY", "ETC"}   # 4종 항상 존재
    assert cats["GROCERY"]["amount"] == 68400
    assert cats["GROCERY"]["ratio"] == round(68400 / 103400, 4)
    assert cats["DELIVERY"] == {"category": "DELIVERY", "amount": 0, "ratio": 0.0}  # 미지출 0
    assert conn.executed[0][1] == (7, date(2026, 7, 1))            # user_id + month 1일(A01)


def test_breakdown_empty_month_zero_total(client):
    conn = FakeConn(responses=[])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/expenses/breakdown?month=2026-07")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert all(c["amount"] == 0 and c["ratio"] == 0.0 for c in body["categories"])  # 분모 0 회피


def test_breakdown_bad_month_422(client):
    OV[get_conn] = lambda: FakeConn(responses=[])
    OV[get_current_user] = lambda: 7
    assert client.get("/api/expenses/breakdown?month=2026-13").status_code == 422


def test_breakdown_requires_auth(client):
    assert client.get("/api/expenses/breakdown?month=2026-07").status_code == 401


# ── #32 POST mealplan/recommend (pantry seam + 순수 랭킹) ────────────────────
def test_recommend_ranks_with_pantry(client):
    # 재고 10(임박)·20 보유. 후보: 레시피7(10,20 전부보유)·9(10,99 절반).
    cand_rows = [
        {"recipe_id": 7, "recipe_name": "두부김치", "item_id": 10, "ing_cost": 300},
        {"recipe_id": 7, "recipe_name": "두부김치", "item_id": 20, "ing_cost": 150},
        {"recipe_id": 9, "recipe_name": "파전", "item_id": 10, "ing_cost": 300},
        {"recipe_id": 9, "recipe_name": "파전", "item_id": 99, "ing_cost": 500},
    ]
    OV[get_conn_opener] = lambda: opener(FakeConn(responses=cand_rows))
    OV[get_current_user] = lambda: 7
    OV[get_pantry_provider] = lambda: FakePantryProvider(
        stock=[stock(10, expiring=True), stock(20)])
    OV[get_exclusion_provider] = lambda: FakeExclusionProvider()   # 제외 없음
    r = client.post("/api/mealplan/recommend", json={"budget": 100000})
    assert r.status_code == 200
    body = r.json()
    assert body["note"] is None
    ids = [x["recipe_id"] for x in body["recommendations"]]
    assert ids == [7, 9]                          # 커버리지 1.0 인 7 이 먼저
    assert body["recommendations"][0]["coverage"] == 1.0
    assert body["recommendations"][0]["est_cost"] == 450
    assert body["recommendations"][0]["expiring_used"] == 1   # 임박재료 10 사용


def test_recommend_passes_excluded_items_to_query(client):
    # 제외(회피) 재료가 후보 쿼리 exclude_ids 파라미터로 전달되는지 (SQL 바인딩 검증).
    cand_rows = [{"recipe_id": 7, "recipe_name": "두부김치", "item_id": 10, "ing_cost": 300}]
    conn = FakeConn(responses=cand_rows)
    OV[get_conn_opener] = lambda: opener(conn)
    OV[get_current_user] = lambda: 7
    OV[get_pantry_provider] = lambda: FakePantryProvider(stock=[stock(10)])
    OV[get_exclusion_provider] = lambda: FakeExclusionProvider(excluded=[99])
    r = client.post("/api/mealplan/recommend", json={})
    assert r.status_code == 200
    _sql, params = conn.executed[0]
    assert [99] in params                         # exclude_ids=[99] 가 쿼리에 바인딩


def test_recommend_degrades_when_exclusion_unavailable(client):
    # 제외 seam 미가용이어도 추천은 제외 없이 진행(빈 리스트로 degrade).
    cand_rows = [{"recipe_id": 7, "recipe_name": "두부김치", "item_id": 10, "ing_cost": 300}]
    conn = FakeConn(responses=cand_rows)
    OV[get_conn_opener] = lambda: opener(conn)
    OV[get_current_user] = lambda: 7
    OV[get_pantry_provider] = lambda: FakePantryProvider(stock=[stock(10)])
    OV[get_exclusion_provider] = lambda: FakeExclusionProvider(unavailable=True)
    r = client.post("/api/mealplan/recommend", json={})
    assert r.status_code == 200
    assert conn.executed[0][1][1] == []           # exclude_ids 자리에 빈 리스트


def test_recommend_degraded_when_pantry_unavailable(client):
    OV[get_conn_opener] = lambda: opener(FakeConn())   # 도달 안 함(도달 전 degrade)
    OV[get_current_user] = lambda: 7
    OV[get_pantry_provider] = lambda: FakePantryProvider(unavailable=True)
    r = client.post("/api/mealplan/recommend", json={})
    assert r.status_code == 200
    assert r.json()["recommendations"] == []
    assert "unavailable" in r.json()["note"]


def test_recommend_empty_pantry_note(client):
    OV[get_conn_opener] = lambda: opener(FakeConn())
    OV[get_current_user] = lambda: 7
    OV[get_pantry_provider] = lambda: FakePantryProvider(stock=[])
    r = client.post("/api/mealplan/recommend", json={})
    assert r.status_code == 200
    assert r.json()["recommendations"] == []
    assert r.json()["note"] is not None


def test_recommend_requires_auth(client):
    assert client.post("/api/mealplan/recommend", json={}).status_code == 401


# ── 클릭스트림 ADD_CART 이벤트 발행 (events.py) ──
def test_build_add_cart_event_contract():
    from app import events
    ev = events.build_add_cart_event(user_id=7, recipe_id=10, session_id="s1")
    assert ev["event_type"] == "ADD_CART" and ev["user_id"] == 7 and ev["recipe_id"] == 10
    assert ev["item_id"] is None and ev["event_id"] and ev["occurred_at"]   # 계약 필드


async def test_emit_add_cart_noop_when_disabled():   # asyncio_mode=auto (pytest.ini)
    # 🔴 C-88 로 async 가 됐다 — await 하지 않으면 코루틴이 안 돌아 **테스트가 무의미**해진다
    #    (실측: "coroutine 'emit_add_cart' was never awaited" RuntimeWarning).
    from app import events
    from app.config import Settings
    s = Settings()   # event_produce_enabled 기본 False
    await events.emit_add_cart(s, 7, 10, "s1")   # 예외 없이 무동작(Kafka 미접속)


def test_flush_noop_when_producer_never_created():
    from app import events
    assert events._producer is None      # 미발행 배포 = 프로듀서 미생성
    events.flush()                       # 예외 없이 무동작


def test_flush_drains_buffer(monkeypatch):
    """linger.ms 버퍼에 남은 이벤트를 종료 전에 밀어낸다 (미호출 시 ADD_CART 유실)."""
    from app import events

    class FakeProducer:
        def __init__(self): self.flushed = None
        def flush(self, timeout): self.flushed = timeout

    fake = FakeProducer()
    monkeypatch.setattr(events, "_producer", fake)
    events.flush(timeout=1.5)
    assert fake.flushed == 1.5


def test_flush_swallows_producer_error(monkeypatch):
    """종료 경로 — flush 실패가 셧다운을 막지 않는다 (발행과 동일한 best-effort)."""
    from app import events

    class BrokenProducer:
        def flush(self, timeout): raise RuntimeError("broker gone")

    monkeypatch.setattr(events, "_producer", BrokenProducer())
    events.flush()                       # 예외가 새어나오지 않음


# ── ML 재랭킹 호출 (ranking_client.py, B3) ──
def test_ranking_reorder_by_serving_order():
    from app import ranking_client
    class R:
        def __init__(self, i): self.id = i
    out = ranking_client.reorder([R(10), R(11), R(12)], [12, 10])
    assert [r.id for r in out] == [12, 10, 11]     # order대로 앞, 없는 건 뒤 원순서


async def test_ranking_personalize_noop_when_disabled():
    from app import ranking_client
    from app.config import Settings
    class R:
        id = 10; coverage = 0.5; expiring_used = 1; est_cost = 500; score = 8.0
    # ranking_ml_enabled 기본 False → 서빙 호출 없이 None(규칙순 유지)
    assert await ranking_client.personalize(Settings(), 7, [R()], 10000) is None
