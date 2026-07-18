"""consume_user_event 순수 로직(to_params) 단위 테스트.

confluent_kafka는 로컬 미설치(CI만)라, 컨슈머 루프와 무관한 순수 검증을 위해 스텁 주입 후 import.
"""
import sys
import types
from pathlib import Path

# confluent_kafka 스텁 — _kafka import가 로컬에서 깨지지 않게(순수 로직만 검증).
if "confluent_kafka" not in sys.modules:
    ck = types.ModuleType("confluent_kafka")
    ck.Consumer = ck.Producer = object
    adm = types.ModuleType("confluent_kafka.admin")
    adm.AdminClient = adm.NewTopic = object
    sys.modules["confluent_kafka"] = ck
    sys.modules["confluent_kafka.admin"] = adm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingest"))

import pytest  # noqa: E402

from consume_user_event import _VALID_EVENTS, to_params  # noqa: E402


def test_valid_events_match_schema_check():
    # activity.user_event CHECK(event_type IN ...)와 동일해야 함
    assert _VALID_EVENTS == {"VIEW", "ADD_CART", "NOTIF_CLICK"}


def test_to_params_maps_fields():
    rec = {"event_id": "e1", "user_id": 7, "session_id": "s1", "event_type": "ADD_CART",
           "recipe_id": 10, "occurred_at": "2026-07-18T00:00:00Z", "context": {"rank": 1}}
    p = to_params(rec)
    assert p["event_id"] == "e1" and p["user_id"] == 7 and p["event_type"] == "ADD_CART"
    assert p["recipe_id"] == 10 and p["item_id"] is None      # 없는 키는 None
    assert p["context"] is not None                            # jsonb 래핑


def test_to_params_context_none_when_absent():
    p = to_params({"event_id": "e", "user_id": 1, "event_type": "VIEW",
                   "occurred_at": "2026-07-18T00:00:00Z"})
    assert p["context"] is None and p["session_id"] is None


def test_to_params_rejects_invalid_event_type():
    with pytest.raises(ValueError):
        to_params({"event_id": "e", "user_id": 1, "event_type": "CLICK",
                   "occurred_at": "2026-07-18T00:00:00Z"})


def test_to_params_missing_required_key_raises():
    with pytest.raises(KeyError):
        to_params({"user_id": 1, "event_type": "VIEW"})   # event_id·occurred_at 누락


# ── produce_user_event (프로듀서 헬퍼) ──
from produce_user_event import build_event, emit_user_event  # noqa: E402


class _FakeProducer:
    def __init__(self): self.sent = []
    def produce(self, topic, key, value): self.sent.append((topic, key, value))
    def poll(self, t): pass


def test_build_event_maps_and_generates_event_id():
    ev = build_event(user_id=7, event_type="ADD_CART", recipe_id=10,
                     session_id="s", occurred_at="2026-07-18T00:00:00Z")
    assert ev["user_id"] == 7 and ev["event_type"] == "ADD_CART" and ev["recipe_id"] == 10
    assert ev["event_id"] and ev["item_id"] is None       # event_id 자동, 없는 필드 None


def test_build_event_rejects_bad_type():
    with pytest.raises(ValueError):
        build_event(user_id=1, event_type="CLICK", occurred_at="t")


def test_emit_produces_with_user_id_key():
    import json as _json
    fp = _FakeProducer()
    ev = build_event(user_id=42, event_type="VIEW", recipe_id=5, occurred_at="2026-07-18T00:00:00Z")
    emit_user_event(ev, prod=fp)
    assert len(fp.sent) == 1
    topic, key, value = fp.sent[0]
    assert topic == "events.user.activity" and key == "42"
    assert _json.loads(value)["recipe_id"] == 5           # 컨슈머 to_params와 왕복 호환


# ── prune_user_data (보존정리 배치) ──
def test_prune_user_data_retention_targets():
    import prune_user_data as p
    tables = [t for t, _ in p._RETENTION]
    assert "activity.user_event" in tables and "activity.recipe_impression" in tables
    assert "chat.chat_message" in tables
    assert p.RETENTION_DAYS >= 90                       # §7 기본 보존창(90~180)


def test_prune_once_deletes_and_commits_with_fake_conn():
    import prune_user_data as p

    class _Cur:
        rowcount = 3
        def execute(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
    class _Tx:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    class _Conn:
        def __init__(self): self.committed = False
        def cursor(self): return _Cur()
        def transaction(self): return _Tx()
        def commit(self): self.committed = True
        def close(self): pass

    c = _Conn()
    total = p.prune_once(conn=c)
    assert c.committed is True and total > 0             # 삭제 카운트 합산 + 커밋
