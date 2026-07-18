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
