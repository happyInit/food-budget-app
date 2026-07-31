"""DLQ 헬퍼 — **안전 속성**을 고정한다 (#252).

이 모듈의 모든 판단은 "확실할 때만 격리"다. 아래 테스트가 깨지면 그 성질이 무너진 것이다.
드라이버(psycopg·confluent_kafka) 없이 검증 가능해야 하므로 예외는 이름으로 판정한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _dlq  # noqa: E402


# ── 가짜 예외 (드라이버 없이 이름만 흉내) ──────────────────────────────────────
def _exc(name, base=Exception, msg="boom"):
    return type(name, (base,), {})(msg)


class _Msg:
    def __init__(self, key=b"k", value=b"{}", headers=None, part=2, off=42):
        self._k, self._v, self._h, self._p, self._o = key, value, headers, part, off

    def key(self): return self._k
    def value(self): return self._v
    def headers(self): return self._h
    def partition(self): return self._p
    def offset(self): return self._o


class _Prod:
    def __init__(self, remaining=0):
        self.sent, self._remaining = [], remaining

    def produce(self, topic, key=None, value=None, headers=None):
        self.sent.append({"topic": topic, "key": key, "value": value, "headers": headers})

    def flush(self, timeout=None):
        return self._remaining


# ── 분류 ───────────────────────────────────────────────────────────────────────
def test_permanent_failures_are_quarantined():
    """재시도해도 절대 성공하지 않는 것 — payload 파손·제약 위반."""
    for name in ("JSONDecodeError", "KeyError", "ValueError",
                 "IntegrityError", "ForeignKeyViolation", "NotNullViolation"):
        assert _dlq.is_permanent(_exc(name)), name


def test_transient_failures_are_never_quarantined():
    """🔴 인프라 순단은 재시도가 정당하다 — 격리하면 **멀쩡한 메시지를 버린다.**"""
    for name in ("OperationalError", "InterfaceError", "KafkaException", "TimeoutError"):
        assert not _dlq.is_permanent(_exc(name)), name


def test_unknown_exceptions_default_to_raise():
    """🔴 **모르는 예외는 격리하지 않는다.** 화이트리스트가 이 장치의 안전 속성이다.

    모르는 것을 조용히 버리면 DLQ 가 새로운 유실 경로가 된다.
    """
    for name in ("SomeNewError", "WeirdVendorError", "RuntimeError"):
        assert not _dlq.is_permanent(_exc(name)), name


def test_transient_wins_when_inheritance_overlaps():
    """상속으로 두 목록에 걸리면 **일시(안전측)** 로 판정한다."""
    perm = type("IntegrityError", (Exception,), {})
    mixed = type("OperationalError", (perm,), {})     # 일시가 영구를 상속하는 가상 케이스
    assert not _dlq.is_permanent(mixed("x"))


# ── 발행 ───────────────────────────────────────────────────────────────────────
def test_original_message_is_preserved_verbatim():
    """원본 key·value 를 **가공하지 않는다** — 재투입이 곧 원본 재생산이어야 한다."""
    p, m = _Prod(), _Msg(key=b"src:1", value=b'{"a":1}')
    _dlq.send_to_dlq(p, m, _exc("ValueError"), "retail-refiner", "retail.crawl.raw")
    sent = p.sent[0]
    assert sent["topic"] == "retail.crawl.raw.dlq"
    assert sent["key"] == b"src:1" and sent["value"] == b'{"a":1}'


def test_context_is_carried_in_headers_with_original_headers_kept():
    """원본 헤더를 보존하고 `dlq.*` 만 덧붙인다. 오프셋은 사후 조사·중복 판정에 쓴다."""
    m = _Msg(headers=[("source", b"oasis")])
    h = dict(_dlq.build_headers(m, _exc("IntegrityError", msg="fk"), "c", "t"))
    assert h["source"] == b"oasis"
    assert h["dlq.error"] == b"IntegrityError"
    assert h["dlq.partition"] == b"2" and h["dlq.offset"] == b"42"
    assert b"fk" in h["dlq.detail"]


def test_undelivered_dlq_raises_instead_of_advancing():
    """🔴 발행이 확인 안 되면 **진행하면 안 된다** — 메시지가 진짜로 사라진다.

    브로커가 `auto.create.topics.enable=false` 라 **토픽이 없으면 produce 는 성공한 것처럼
    보이고 flush 만 미전달을 남긴다**(2026-07-29 실측). 그래서 flush 반환값을 확인한다.
    """
    import pytest
    with pytest.raises(_dlq.DlqDeliveryFailed):
        _dlq.send_to_dlq(_Prod(remaining=1), _Msg(), _exc("ValueError"), "c", "t")


def test_quarantine_returns_false_for_transient_without_producing():
    """일시 실패는 DLQ 를 건드리지도 않는다(호출측이 raise 한다)."""
    p = _Prod()
    assert _dlq.quarantine(p, _Msg(), _exc("OperationalError"), "c", "t") is False
    assert p.sent == []


# ── savepoint ──────────────────────────────────────────────────────────────────
class _Cur:
    def __init__(self, fail_rollback=False):
        self.sql, self._fr = [], fail_rollback

    def execute(self, q, *a):
        self.sql.append(q)
        if self._fr and "ROLLBACK TO SAVEPOINT" in q:
            raise RuntimeError("connection gone")


def test_savepoint_released_on_success():
    cur = _Cur()
    with _dlq.record_savepoint(cur):
        cur.execute("insert ...")
    assert cur.sql[0].startswith("SAVEPOINT") and cur.sql[-1].startswith("RELEASE SAVEPOINT")


def test_savepoint_rolls_back_only_that_record():
    """🔴 `conn.rollback()` 이면 **같은 배치의 앞선 정상 레코드까지** 사라진다.

    그 건들은 오프셋이 나중에 커밋되므로 조용히 유실된다 — savepoint 가 필수인 이유다.
    """
    import pytest
    cur = _Cur()
    with pytest.raises(ValueError):
        with _dlq.record_savepoint(cur):
            raise ValueError("boom")
    assert any(q.startswith("ROLLBACK TO SAVEPOINT") for q in cur.sql)
    assert not any(q.startswith("RELEASE") for q in cur.sql)


def test_rollback_failure_does_not_mask_original_error():
    """커넥션이 끊겨 롤백도 실패하면 **원래 예외**를 올린다 — 원인이 가려지면 진단 불가."""
    import pytest
    with pytest.raises(ValueError):
        with _dlq.record_savepoint(_Cur(fail_rollback=True)):
            raise ValueError("original")
