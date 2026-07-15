"""라우터 골든 테스트 — 주입 seam으로 실 DB·실 JWT 없이 핸들러를 통째 검증.
★ override 패턴(account 복제):
   app.dependency_overrides[get_conn] = lambda: FakeConn([...])  → DB 없이 쿼리 결과 주입
   app.dependency_overrides[get_current_user] = lambda: 7        → 인증 통과 가장
FakeConn 응답은 dict (풀 row_factory=dict_row와 동일 shape).
검증 항목(태스크 요구): (a) SQL 매핑·정상응답 (b) 에러코드 404 (c) 인증 없이 401
(d) 소유권 — 남의 알림 읽음 시 쿼리 None → 404 + WHERE user_id 파라미터 실렸는지 확인.
"""
from __future__ import annotations

from datetime import datetime, timezone

import app.main as main_mod
from app.context import get_conn, get_current_user
from tests.fakes import FakeConn

OV = main_mod.app.dependency_overrides

CREATED = datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)


def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text


# ── #41 목록 ──────────────────────────────────────────────────────────────
def test_list_notifications_maps_rows(client):
    conn = FakeConn(responses=[
        {"id": 2, "type": "HOTDEAL", "title": "감자 핫딜", "body": "20% 할인",
         "payload": {"item_id": 10}, "is_read": False, "created_at": CREATED},
        {"id": 1, "type": "BUDGET", "title": "예산 80% 소진", "body": None,
         "payload": None, "is_read": True, "created_at": CREATED},
    ])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/notifications")
    assert r.status_code == 200
    data = r.json()["notifications"]
    assert [n["id"] for n in data] == [2, 1]
    assert data[0]["type"] == "HOTDEAL"
    assert data[0]["payload"] == {"item_id": 10}
    assert data[1]["body"] is None
    # 소유권(A01): user_id 가 WHERE 파라미터로 실렸는지
    sql, params = conn.executed[0]
    assert "where user_id = %s" in sql
    assert params == (7,)
    assert "and is_read = false" not in sql          # unread 미지정 → 필터 없음


def test_list_unread_filter_applied(client):
    conn = FakeConn(responses=[])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.get("/api/notifications?unread=true")
    assert r.status_code == 200
    assert r.json() == {"notifications": []}
    sql, params = conn.executed[0]
    assert "and is_read = false" in sql              # unread=true → 안 읽은 것만
    assert "order by created_at desc" in sql
    assert params == (7,)


def test_list_requires_auth(client):
    # get_current_user 미오버라이드 → 실제 Bearer 검증 → 토큰 없음 → 401
    assert client.get("/api/notifications").status_code == 401


# ── #42 읽음 처리 ─────────────────────────────────────────────────────────
def test_mark_read_ok(client):
    conn = FakeConn(responses=[{"id": 5}])           # UPDATE ... RETURNING id
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.patch("/api/notifications/5/read")
    assert r.status_code == 200
    assert r.json() == {"id": 5, "is_read": True}
    sql, params = conn.executed[0]
    assert "update notify.notification set is_read = true" in sql
    assert "where id = %s and user_id = %s" in sql   # 소유권
    assert params == (5, 7)                           # user_id=7 이 바인딩됨


def test_mark_read_others_notification_404(client):
    # 남의(또는 없는) 알림 → WHERE user_id 로 매치 0 → RETURNING None → 404
    conn = FakeConn(responses=[])
    OV[get_conn] = lambda: conn
    OV[get_current_user] = lambda: 7
    r = client.patch("/api/notifications/999/read")
    assert r.status_code == 404
    _, params = conn.executed[0]
    assert params == (999, 7)


def test_mark_read_requires_auth(client):
    assert client.patch("/api/notifications/5/read").status_code == 401
