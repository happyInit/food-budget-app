"""운반 계층(S3·SQS) 단위 테스트 — DB·AWS 무의존 (services/CONVENTIONS.md 의 DB-free 테스트 방침).

여기서 지키려는 계약 3가지:
  ① 객체 키 ↔ source 왕복 — 어긋나면 `crawl_raw` 유니크 키가 갈려 **같은 레코드가 중복 적재**된다
  ② 업로드 전달 판정 — ETag 대조가 빠지면 "올린 셈 친" 실패가 성공으로 마감된다(#558 의 양식)
  ③ 메시지 삭제 시점 — 처리 실패에도 지우면 그 크롤분이 통째로 사라진다
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _s3  # noqa: E402
import _sqs  # noqa: E402


# ── ① 키 규약 ────────────────────────────────────────────────────────────────
def test_incoming_key_round_trips_source():
    key = _s3.incoming_key("retail", "kurly", "20260811T033000Z-pod", day="2026-08-11")
    assert key == "incoming/retail/kurly/2026-08-11/20260811T033000Z-pod.jsonl"
    assert _s3.parse_source(key) == "kurly"


def test_parse_source_rejects_foreign_key():
    # failed/ 객체나 손으로 올린 파일이 컨슈머에 들어오면 조용히 엉뚱한 source 를 쓰면 안 된다
    with pytest.raises(ValueError):
        _s3.parse_source("failed/retail/kurly/2026-08-11/run/000001.json")


def test_failed_key_is_not_under_incoming():
    """🔴 S3 이벤트 필터가 incoming/ 에만 걸려 있다 — 격리본이 그 밑에 들어가면 무한 루프가 된다."""
    key = _s3.failed_key("retail", "oasis", "run-1", 42, day="2026-08-11")
    assert key.startswith("failed/")
    assert not key.startswith("incoming/")
    assert key.endswith("/000042.json")


# ── ② 업로드 전달 판정 ────────────────────────────────────────────────────────
class _StubS3:
    def __init__(self, etag=None):
        self.etag = etag
        self.puts = []

    def put_object(self, **kw):
        self.puts.append(kw)
        digest = hashlib.md5(kw["Body"]).hexdigest()  # noqa: S324
        return {"ETag": f'"{self.etag or digest}"'}

    def get_object(self, **kw):
        return {"Body": self._body}


def test_upload_run_returns_key_when_etag_matches(tmp_path):
    src = tmp_path / "out.jsonl"
    src.write_text('{"a":1}\n{"a":2}\n', encoding="utf-8")
    stub = _StubS3()

    key = _s3.upload_run(src, "retail", "kurly", rid="run-1", s3=stub)

    assert key == _s3.incoming_key("retail", "kurly", "run-1")
    assert stub.puts[0]["Body"] == src.read_bytes()


def test_upload_run_raises_when_etag_differs(tmp_path):
    """전달 미확인은 예외다 — 조용한 성공이 이 파이프라인의 고질적 실패 양식이었다(#558)."""
    src = tmp_path / "out.jsonl"
    src.write_text('{"a":1}\n', encoding="utf-8")

    with pytest.raises(_s3.UploadFailed):
        _s3.upload_run(src, "retail", "kurly", rid="run-1", s3=_StubS3(etag="deadbeef"))


def test_iter_records_skips_blank_lines():
    stub = _StubS3()
    stub._body = type("B", (), {"iter_lines": lambda self: iter([b'{"a":1}', b"", b'{"a":2}'])})()

    got = list(_s3.iter_records("mp-crawl-ap2", "incoming/retail/kurly/d/r.jsonl", s3=stub))

    assert [rec for _, rec in got] == [{"a": 1}, {"a": 2}]
    assert [seq for seq, _ in got] == [0, 2]  # seq = 줄번호 — 격리본 이름이 원본 위치를 가리킨다


# ── ③ 메시지 삭제 시점 ────────────────────────────────────────────────────────
def _event(key="incoming/retail/kurly/2026-08-11/run.jsonl", bucket="mp-crawl-ap2"):
    return json.dumps({"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]})


class _StubSQS:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.deleted = []
        self.extended = []

    def receive_message(self, **kw):
        if not self.bodies:
            return {}
        return {"Messages": [{"Body": self.bodies.pop(0), "ReceiptHandle": "rh"}]}

    def delete_message(self, **kw):
        self.deleted.append(kw["ReceiptHandle"])

    def change_message_visibility(self, **kw):
        self.extended.append(kw["VisibilityTimeout"])


class _NullLog:
    def __getattr__(self, _name):
        return lambda *a, **k: None


def test_consume_deletes_after_successful_handling():
    sqs = _StubSQS([_event()])
    seen = []

    _sqs.consume(lambda b, k, hb: seen.append((b, k)), log=_NullLog(), component="t",
                 url="q", idle_exit=1, sqs=sqs)

    assert seen == [("mp-crawl-ap2", "incoming/retail/kurly/2026-08-11/run.jsonl")]
    assert sqs.deleted == ["rh"]


def test_consume_keeps_message_when_handler_fails():
    """🔴 실패한 객체를 지우면 그 크롤분이 사라진다. 남겨야 가시성 만료 후 재전달된다."""
    sqs = _StubSQS([_event()])

    def boom(*_a):
        raise RuntimeError("db down")

    with pytest.raises(RuntimeError):
        _sqs.consume(boom, log=_NullLog(), component="t", url="q", idle_exit=1, sqs=sqs)

    assert sqs.deleted == []


def test_consume_drops_s3_test_event():
    """S3 는 알림을 붙일 때 Records 없는 TestEvent 를 한 번 보낸다. 안 지우면 DLQ 로 간다."""
    sqs = _StubSQS([json.dumps({"Service": "Amazon S3", "Event": "s3:TestEvent"})])
    called = []

    _sqs.consume(lambda *a: called.append(a), log=_NullLog(), component="t",
                 url="q", idle_exit=1, sqs=sqs)

    assert called == []
    assert sqs.deleted == ["rh"]


def test_consume_url_decodes_object_key():
    sqs = _StubSQS([_event(key="incoming/recipe/10K/2026-08-11/run%2Bx.jsonl")])
    seen = []

    _sqs.consume(lambda b, k, hb: seen.append(k), log=_NullLog(), component="t",
                 url="q", idle_exit=1, sqs=sqs)

    assert seen == ["incoming/recipe/10K/2026-08-11/run+x.jsonl"]
