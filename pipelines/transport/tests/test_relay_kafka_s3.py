"""crawl-s3-relay 단위 테스트 — Kafka·AWS 무의존 (DB-free 방침).

여기서 지키려는 계약 4가지:
  ① 토픽 → 스트림 매핑 — 어긋나면 S3 이벤트가 **엉뚱한 큐**로 가고 객체가 조용히 안 처리된다
  ② source 기본값 — 구 컨슈머와 달라지면 `crawl_raw` 유니크 키가 갈려 **중복 적재**된다
  🔴 ③ 업로드 확인 → 오프셋 커밋 순서 — 뒤집히면 그 크롤분이 **통째로 사라진다**
  ④ poison 메시지가 파티션을 막지 않는다
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "stream"))
import relay_kafka_s3 as relay  # noqa: E402


class _Msg:
    def __init__(self, topic, payload, source=b"kurly", err=None, raw=None):
        self._topic, self._err = topic, err
        self._value = raw if raw is not None else json.dumps(payload).encode()
        self._headers = [("source", source)] if source is not None else None

    def topic(self):
        return self._topic

    def value(self):
        return self._value

    def headers(self):
        return self._headers

    def error(self):
        return self._err


class _Consumer:
    """poll() 이 준비된 메시지를 차례로 내주고, 소진되면 None(유휴)을 낸다."""

    def __init__(self, msgs):
        self._msgs = list(msgs)
        self.commits = 0
        self.closed = False
        self.subscribed = None

    def subscribe(self, topics):
        self.subscribed = topics

    def poll(self, _timeout):
        return self._msgs.pop(0) if self._msgs else None

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def _run(msgs, uploader, **kw):
    c = _Consumer(msgs)
    out = relay.run(consumer_factory=lambda _g: c, uploader=uploader,
                    idle_exit=kw.pop("idle_exit", 1.0), bucket_hint="mp-crawl-ap2", **kw)
    return c, out


def _ok_uploader(calls):
    def _up(path, stream, source, rid=None):
        calls.append((stream, source, Path(path).read_text(encoding="utf-8")))
        return f"incoming/{stream}/{source}/2026-08-16/{rid}.jsonl"
    return _up


# ── ① 토픽 → 스트림 매핑 ─────────────────────────────────────────────────────
def test_stream_map_matches_key_convention():
    """🔴 SQS 큐 3개와 S3 이벤트 prefix 가 이 세 이름에 물려 있다."""
    assert set(relay.STREAMS.values()) == {"retail", "deal", "recipe"}
    assert relay.STREAMS["retail.crawl.raw"] == "retail"
    assert relay.STREAMS["retail.deal.raw"] == "deal"
    assert relay.STREAMS["recipe.crawl.raw"] == "recipe"


def test_deal_topic_does_not_land_in_retail_stream():
    """딜이 retail 로 가면 PG 는 맞지만 **Redis 핫딜 ZSET 이 영영 빈다**(deal-notifier 만 push)."""
    calls = []
    _run([_Msg("retail.deal.raw", {"product_id": 1})], _ok_uploader(calls))
    assert [c[0] for c in calls] == ["deal"]


# ── ② source 기본값 ──────────────────────────────────────────────────────────
def test_source_comes_from_header():
    assert relay._source(_Msg("retail.crawl.raw", {}, source=b"kurly")) == "kurly"


def test_source_default_matches_legacy_consumer():
    """🔴 구 `consume_retail.py` 의 기본값이 `oasis` 다. 여기서만 다르면 중복 적재가 난다."""
    assert relay._source(_Msg("retail.crawl.raw", {}, source=None)) == "oasis"


def test_batches_split_by_stream_and_source():
    calls = []
    _run([_Msg("retail.crawl.raw", {"product_id": 1}, source=b"kurly"),
          _Msg("retail.crawl.raw", {"product_id": 2}, source=b"oasis"),
          _Msg("retail.crawl.raw", {"product_id": 3}, source=b"kurly")], _ok_uploader(calls))
    by_source = {c[1]: c[2] for c in calls}
    assert set(by_source) == {"kurly", "oasis"}
    assert len(by_source["kurly"].strip().splitlines()) == 2
    assert len(by_source["oasis"].strip().splitlines()) == 1


def test_uploaded_body_is_jsonl_of_original_payloads():
    """리파이너가 받는 것이 크롤러가 보낸 것과 같아야 한다 — 여기서 형식이 바뀌면 적재가 깨진다."""
    calls = []
    _run([_Msg("recipe.crawl.raw", {"title": "김치찌개", "n": 1}, source=b"10K")], _ok_uploader(calls))
    assert json.loads(calls[0][2].strip()) == {"title": "김치찌개", "n": 1}


# ── 🔴 ③ 업로드 확인 → 커밋 순서 ─────────────────────────────────────────────
def test_commit_happens_only_after_upload():
    order = []
    c = _Consumer([_Msg("retail.crawl.raw", {"product_id": 1})])
    c.commit = lambda: order.append("commit")  # type: ignore[method-assign]

    def _up(path, stream, source, rid=None):
        order.append("upload")
        return "incoming/x.jsonl"

    relay.run(consumer_factory=lambda _g: c, uploader=_up, idle_exit=1.0,
              bucket_hint="mp-crawl-ap2")
    assert order == ["upload", "commit"], "업로드 전에 커밋하면 그 크롤분이 사라진다"


def test_upload_failure_blocks_commit():
    """🔴 이 테스트가 유실 방지의 핵심이다 — 실패했는데 오프셋이 전진하면 재전달이 안 온다."""
    def _boom(path, stream, source, rid=None):
        raise RuntimeError("etag mismatch")

    c = _Consumer([_Msg("retail.crawl.raw", {"product_id": 1})])
    with pytest.raises(RuntimeError):
        relay.run(consumer_factory=lambda _g: c, uploader=_boom, idle_exit=1.0,
                  bucket_hint="mp-crawl-ap2")
    assert c.commits == 0
    assert c.closed, "예외 경로에서도 컨슈머는 닫아야 한다"


def test_no_commit_when_nothing_consumed():
    """빈 실행이 오프셋을 건드리면 안 된다 — 빈 객체를 올리는 것도 금지(큐에 잡음이 된다)."""
    calls = []
    c, (objects, records) = _run([], _ok_uploader(calls))
    assert (objects, records, c.commits, calls) == (0, 0, 0, [])


# ── ④ poison 메시지 ──────────────────────────────────────────────────────────
def test_bad_json_is_skipped_not_wedged():
    """재시도해도 같은 결과다 — 멈추면 릴레이가 그 파티션에 영원히 갇힌다."""
    calls = []
    _run([_Msg("retail.crawl.raw", None, raw=b"{not json"),
          _Msg("retail.crawl.raw", {"product_id": 2})], _ok_uploader(calls))
    assert len(calls) == 1
    assert len(calls[0][2].strip().splitlines()) == 1


def test_kafka_error_message_is_skipped():
    calls = []
    _run([_Msg("retail.crawl.raw", None, err=_FakeErr()),
          _Msg("retail.crawl.raw", {"product_id": 2})], _ok_uploader(calls))
    assert len(calls) == 1


class _FakeErr:
    def code(self):
        return -191


def test_max_records_forces_intermediate_flush():
    """객체가 무한정 커지지 않아야 한다 — 리파이너가 객체 하나를 통째로 다시 읽기 때문."""
    calls = []
    msgs = [_Msg("retail.crawl.raw", {"product_id": i}) for i in range(5)]
    c, _ = _run(msgs, _ok_uploader(calls), max_records=2)
    assert len(calls) == 3          # 2 + 2 + 1
    assert c.commits == 3
