"""consumer(group_id, bootstrap=None) — 브로커 주입 vs 폴백 (#557 prep).

읽기=AWS/쓰기=온프렘 비대칭을 위해 consumer 만 bootstrap 주입 가능해야 한다.
기존 5종 컨슈머(group_id 만 전달)는 폴백으로 **동일 동작**임을 고정한다.
confluent_kafka 없이 검증 — Consumer 를 캡처 스텁으로 대체.
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _CapturedConsumer:
    """confluent_kafka.Consumer 대체 — 넘어온 config 를 그대로 보관."""
    def __init__(self, conf):
        self.conf = conf


# _kafka 는 confluent_kafka 를 import 한다 → 드라이버 없이 테스트하도록 스텁 주입(임포트 전).
if "confluent_kafka" not in sys.modules:
    _ck = types.ModuleType("confluent_kafka")
    _ck.Consumer = _CapturedConsumer
    _ck.Producer = object
    _admin = types.ModuleType("confluent_kafka.admin")
    _admin.AdminClient = object
    _ck.admin = _admin
    sys.modules["confluent_kafka"] = _ck
    sys.modules["confluent_kafka.admin"] = _admin

import _kafka  # noqa: E402


def _patch():
    orig = _kafka.Consumer
    _kafka.Consumer = _CapturedConsumer
    return orig


def test_default_falls_back_to_env_bootstrap():
    orig = _patch()
    try:
        c = _kafka.consumer("g1")
        assert c.conf["bootstrap.servers"] == _kafka.BOOTSTRAP  # 기존 5종과 동일
        assert c.conf["group.id"] == "g1"
        assert c.conf["enable.auto.commit"] is False           # 수동커밋 유지
    finally:
        _kafka.Consumer = orig


def test_explicit_bootstrap_is_injected():
    orig = _patch()
    try:
        c = _kafka.consumer("g2", bootstrap="aws-broker:9092")
        assert c.conf["bootstrap.servers"] == "aws-broker:9092"  # 주입값 우선
        assert c.conf["group.id"] == "g2"
    finally:
        _kafka.Consumer = orig


def test_empty_bootstrap_falls_back():
    orig = _patch()
    try:
        c = _kafka.consumer("g3", bootstrap="")   # 빈 문자열 = 미설정 취급
        assert c.conf["bootstrap.servers"] == _kafka.BOOTSTRAP
    finally:
        _kafka.Consumer = orig


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fails = 0
    for fn in fns:
        try:
            fn(); print(f"  ✅ {fn.__name__}")
        except Exception:  # noqa: BLE001
            fails += 1; print(f"  ❌ {fn.__name__}"); traceback.print_exc()
    print(f"\n{len(fns)-fails}/{len(fns)} passed")
    raise SystemExit(1 if fails else 0)
