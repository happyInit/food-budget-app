"""Kafka 전달 판정 — **유실을 성공으로 마감하지 않는다** (#558).

여기서 고정하는 성질은 하나다:

    🔴 `flush()` 가 0 을 돌려줘도 메시지는 잃었을 수 있다.

실측(2026-08-09 · confluent-kafka 2.15.0 / librdkafka 2.15.0) — 닿지 않는 브로커로 3건
produce 하고 `delivery.timeout.ms=3000` 으로 기다리면:

    flush remaining = 0     ← "다 나갔다"로 읽힌다
    delivery callbacks = 3  ← 전부 _MSG_TIMED_OUT (영구 실패)

아래 스텁은 그 관측을 그대로 흉내낸다(브로커·드라이버 무의존).
실행: python -m pytest pipelines/stream/tests -q
"""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _delivery  # noqa: E402
import _dlq       # noqa: E402


class FakeKafkaError(Exception):
    """confluent_kafka.KafkaError 대역 — 이름과 문자열만 흉내낸다."""

    def __init__(self, name="_MSG_TIMED_OUT", msg="Local: Message timed out", fatal=False):
        super().__init__(msg)
        self._name, self._fatal = name, fatal

    def name(self):
        return self._name

    def fatal(self):
        return self._fatal


class FakeMsg:
    def __init__(self, topic="retail.crawl.raw", key=b"k", value=b"{}", headers=None):
        self._t, self._k, self._v, self._h = topic, key, value, headers

    def topic(self): return self._t
    def key(self): return self._k
    def value(self): return self._v
    def headers(self): return self._h
    def partition(self): return 0
    def offset(self): return 7


class StubProducer:
    """librdkafka 의 **관측된 동작**을 그대로 흉내낸다.

    - `produce()` 는 로컬 큐에 넣기만 한다(브로커 왕복 없음).
    - `flush()` 는 큐를 비우며 delivery report 를 발행하고 **남은 수**를 돌려준다.
      🔴 실패한 메시지도 **큐에서는 빠진다** — 그래서 전부 실패해도 remaining 은 0 이다.
    """

    def __init__(self, *, err=None, stuck=0, trk=None):
        self.err, self.stuck = err, stuck
        self.trk = trk or _delivery.tracker()
        self.queue = []

    def produce(self, topic, key=None, value=None, headers=None):
        self.queue.append(topic)

    def poll(self, _timeout=0):
        return 0

    def flush(self, _timeout=None):
        delivered, self.queue = self.queue[self.stuck:], self.queue[:self.stuck]
        for topic in delivered:
            self.trk.on_delivery(self.err, FakeMsg(topic))
        return len(self.queue)


@pytest.fixture(autouse=True)
def _fresh_tracker():
    """전역 트래커는 프로세스 공용이라 테스트끼리 새면 안 된다."""
    _delivery.reset_tracker()
    yield
    _delivery.reset_tracker()


# ── 콜백 ───────────────────────────────────────────────────────────────────────

def test_성공은_전달수로_실패는_실패수로_센다():
    t = _delivery.tracker("test")
    t.on_delivery(None, FakeMsg())
    t.on_delivery(FakeKafkaError(), FakeMsg())
    delivered, failed, errors = t.snapshot()
    assert (delivered, failed) == (1, 1)
    assert errors == {"_MSG_TIMED_OUT": 1}


def test_콜백은_어떤_경우에도_예외를_올리지_않는다(monkeypatch):
    """🔴 콜백 예외는 poll()/flush() 밖으로 다시 던져진다 — 관측을 붙였더니 프로듀서가
    죽는 일이 있으면 안 된다."""
    t = _delivery.tracker("test")

    def boom(_component):
        raise RuntimeError("로거가 터졌다")

    monkeypatch.setattr(_delivery, "get_pipeline_logger", boom)
    t.on_delivery(FakeKafkaError(), FakeMsg())      # 예외가 새어나오면 이 줄에서 실패한다
    t.on_error(FakeKafkaError("_ALL_BROKERS_DOWN"))
    assert t.failed == 1


def test_실패_로그는_표본_상한을_넘지_않는다(capsys):
    """브로커가 통째로 죽으면 실패가 레코드 수만큼 나온다 — 전건을 찍으면 원인 줄이 밀린다.

    ⚠️ caplog 로는 못 본다 — 파이프라인 로거는 `propagate=False` 라 루트로 안 올라간다.
       실제로 나가는 곳(stderr JSON)을 그대로 센다.
    """
    t = _delivery.tracker("test")
    for _ in range(_delivery.LOG_SAMPLE + 20):
        t.on_delivery(FakeKafkaError(), FakeMsg())
    lines = [ln for ln in capsys.readouterr().err.splitlines()
             if '"event":"kafka_delivery_failed"' in ln]
    assert len(lines) == _delivery.LOG_SAMPLE
    assert t.failed == _delivery.LOG_SAMPLE + 20      # 로그는 줄여도 **카운트는 전건**이다


# ── 판정 ───────────────────────────────────────────────────────────────────────

def test_flush_가_0을_줘도_전부_실패했으면_유실이다():
    """🔴 이 PR 의 본체. 2026-08-09 실측 그대로다 — remaining 0 · 콜백 실패 3."""
    p = StubProducer(err=FakeKafkaError())
    for _ in range(3):
        p.produce("retail.crawl.raw")

    report = _delivery.finalize(p, produced=3)

    assert report.remaining == 0, "실패한 메시지는 큐에서 빠진다 — 여기가 함정이었다"
    assert report.failed == 3
    assert report.lost == 3
    assert not report.ok, "종전 코드는 이 상태를 result: success 로 마감했다"


def test_큐에_남은_것도_유실로_센다():
    p = StubProducer(stuck=2)
    for _ in range(5):
        p.produce("retail.crawl.raw")
    report = _delivery.finalize(p, produced=5)
    assert (report.delivered, report.remaining, report.lost) == (3, 2, 2)
    assert not report.ok


def test_전건_전달되면_성공이다():
    p = StubProducer()
    for _ in range(4):
        p.produce("retail.crawl.raw")
    report = _delivery.finalize(p, produced=4)
    assert report.ok and report.delivered == 4 and report.lost == 0


def test_produce_호출수와_전달수가_어긋나면_유실로_본다():
    """이슈 ④ — 종전 지표는 produce() **호출 수**였다. 그 간극을 유실로 드러낸다."""
    report = _delivery.DeliveryReport(delivered=90, failed=0, remaining=0, produced=100)
    assert report.unaccounted == 10
    assert report.lost == 10 and not report.ok


def test_emit_은_종료코드를_돌려주고_실패이벤트를_남긴다(caplog):
    log = logging.getLogger("data-pipeline.test-emit")
    bad = _delivery.DeliveryReport(delivered=0, failed=3, remaining=0, produced=3,
                                   errors={"_MSG_TIMED_OUT": 3})
    with caplog.at_level(logging.INFO, logger="data-pipeline.test-emit"):
        assert bad.emit(log, component="poller-kurly") == 1
        assert _delivery.DeliveryReport(delivered=3, failed=0, remaining=0,
                                        produced=3).emit(log, component="poller-kurly") == 0
    events = [r.event for r in caplog.records]
    assert events == ["kafka_delivery_failed", "kafka_produce_succeeded"]
    assert caplog.records[0].delivered_count == 0
    assert caplog.records[0].failed_count == 3


def test_구조화_필드가_로그_허용목록에_있다():
    """🔴 `_observability` 허용목록 밖의 키는 **조용히 버려진다** — 관측을 붙였다고
    믿는 자리가 비어 있게 된다(09037b4 의 failed_categories 가 실제로 그랬다)."""
    import _observability

    keys = _delivery.DeliveryReport(delivered=1, failed=1, remaining=1, produced=3,
                                    errors={"_MSG_TIMED_OUT": 1}).extra()
    missing = set(keys) - set(_observability._OPTIONAL_FIELDS)
    assert not missing, f"JSON 로그에서 사라지는 필드: {missing}"


# ── DLQ — 격리 실패를 격리 성공으로 읽으면 원본까지 잃는다 ──────────────────────

def test_DLQ_는_전달실패를_격리성공으로_읽지_않는다():
    """flush 가 0 을 줘도(=만료 실패) 오프셋을 전진시키면 안 된다."""
    p = StubProducer(err=FakeKafkaError())
    with pytest.raises(_dlq.DlqDeliveryFailed):
        _dlq.send_to_dlq(p, FakeMsg(), ValueError("깨진 payload"),
                         "retail-refiner", "retail.crawl.raw")


def test_DLQ_는_정상_전달이면_격리로_친다():
    p = StubProducer()
    assert _dlq.quarantine(p, FakeMsg(), ValueError("깨진 payload"),
                           "retail-refiner", "retail.crawl.raw") is True
