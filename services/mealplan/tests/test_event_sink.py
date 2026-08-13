"""EVENT_SINK 목적지 선택자 — C-88.

AWS 에는 Kafka 가 없다(C-44). 종전 경로(Kafka → user-event-sink → PG)의 종착지가
`activity.user_event` 라, 중간을 걷어내고 앱이 직접 쓴다.

🔴 이 테스트가 지키는 선:
  ① 기본값이 `kafka` 다 — 안 주면 현행 그대로. 온프렘 ConfigMap 을 안 건드려도 된다(C-72·C-83)
  ② 선택자가 하나라 **dual-write 가 구조적으로 불가능**하다 (C-72 가 상시 병행 미채택)
  ③ pg 경로도 **담기를 막지 않는다** — 실패해도 예외가 안 새어 나간다
  ④ 실패가 **조용하지 않다** — 카운터가 올라간다 (이번 사고의 교훈)

드라이버 없이 돈다 — FakeConn 으로 SQL 호출만 관찰한다(services/CONVENTIONS.md).
"""
from __future__ import annotations

from app import events
from app.config import Settings


class _FakeCursor:
    def __init__(self, sink: list, rowcount: int = 1, exc: BaseException | None = None):
        self._sink, self.rowcount, self._exc = sink, rowcount, exc

    async def execute(self, sql, params=None):
        if self._exc:
            raise self._exc
        self._sink.append((sql, params))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class _FakeTx:
    """savepoint 흉내 — 예외를 삼키지 않고 그대로 올린다(진짜 transaction() 과 같다)."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class FakeConn:
    def __init__(self, rowcount: int = 1, exc: BaseException | None = None):
        self.executed: list = []
        self._rowcount, self._exc = rowcount, exc

    def transaction(self):
        return _FakeTx()

    def cursor(self):
        return _FakeCursor(self.executed, self._rowcount, self._exc)


def _settings(**kw) -> Settings:
    return Settings(event_produce_enabled=True, **kw)


# ── ① 기본값 = kafka (온프렘 무변화) ─────────────────────────────────────
def test_default_sink_is_kafka():
    assert Settings().event_sink == "kafka", "기본값이 바뀌면 온프렘 동작이 바뀐다"


async def test_kafka_sink_does_not_touch_pg(monkeypatch):
    # Kafka 경로에서는 conn 을 줘도 PG 를 건드리면 안 된다 — 그게 dual-write 다.
    monkeypatch.setattr(events, "_get_producer", lambda *_: (_ for _ in ()).throw(RuntimeError("no broker")))
    conn = FakeConn()
    await events.emit_add_cart(_settings(), 7, 10, "s1", conn)
    assert conn.executed == [], "🔴 kafka 인데 PG 에 썼다 = dual-write"


# ── ② pg 경로는 PG 에만 쓴다 ────────────────────────────────────────────
async def test_pg_sink_writes_user_event_and_skips_kafka(monkeypatch):
    called = {"kafka": False}
    monkeypatch.setattr(events, "_get_producer",
                        lambda *_: called.__setitem__("kafka", True))
    conn = FakeConn()
    await events.emit_add_cart(_settings(event_sink="pg"), 7, 10,
                               "3f2b1c8a-9d4e-4a1b-8c7d-5e6f7a8b9c0d", conn)

    assert called["kafka"] is False, "🔴 pg 인데 Kafka 도 불렀다 = dual-write"
    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    assert "activity.user_event" in sql and "on conflict (event_id) do nothing" in sql
    assert params["event_type"] == "ADD_CART" and params["recipe_id"] == 10
    assert params["session_id"] == "3f2b1c8a-9d4e-4a1b-8c7d-5e6f7a8b9c0d"


# ── ③ 담기를 막지 않는다 ────────────────────────────────────────────────
async def test_pg_sink_swallows_failure():
    conn = FakeConn(exc=RuntimeError("permission denied for table user_event"))
    await events.emit_add_cart(_settings(event_sink="pg"), 7, 10, "s1", conn)
    # 예외가 새어 나오면 이 줄에 못 온다 → 담기가 500 이 된다


async def test_pg_sink_without_conn_is_noop_but_counted():
    before = events.counts().get("failure", 0)
    await events.emit_add_cart(_settings(event_sink="pg"), 7, 10, "s1", conn=None)
    assert events.counts()["failure"] == before + 1, "배선 실수가 조용히 지나가면 안 된다"


# ── ④ 게이트는 그대로 (flag OFF · recipe_id 없음) ───────────────────────
async def test_flag_off_writes_nothing():
    conn = FakeConn()
    await events.emit_add_cart(Settings(event_sink="pg"), 7, 10, "s1", conn)  # produce_enabled=False
    assert conn.executed == []


async def test_no_recipe_id_writes_nothing():
    conn = FakeConn()
    await events.emit_add_cart(_settings(event_sink="pg"), 7, None, "s1", conn)
    assert conn.executed == [], "recipe_id 없으면 학습 라벨이 안 되므로 발행하지 않는다"


# ── ⑤ 실패가 조용하지 않다 ──────────────────────────────────────────────
async def test_counters_move_on_success_and_duplicate():
    s = _settings(event_sink="pg")
    ok = events.counts().get("success", 0)
    await events.emit_add_cart(s, 7, 10, "s1", FakeConn(rowcount=1))
    assert events.counts()["success"] == ok + 1

    dup = events.counts().get("duplicate", 0)
    await events.emit_add_cart(s, 7, 10, "s1", FakeConn(rowcount=0))   # ON CONFLICT
    assert events.counts()["duplicate"] == dup + 1
