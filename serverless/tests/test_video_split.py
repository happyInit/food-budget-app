"""접수·워커 분할의 계약 검증 — 설계서 §3 의 "새로 생기는 것 4건" 이 실제로 막히는가.

**왜 이 테스트가 필요한가.** 분할이 깨지는 방식은 전부 *조용하다*:
  · 캐시 키가 접수/워커에서 갈리면 → 락은 걸리는데 캐시가 안 맞아 **영구 중복 분석**
  · 워커가 마지막 시도에서 FAILED 를 안 남기면 → 잡이 `PENDING` 인 채 **유저가 영원히 대기**
  · 재시도가 남았는데 예외를 삼키면 → SQS 가 성공으로 알고 메시지를 지운다(같은 결과)
  · 큐 전송 실패를 안 되돌리면 → **아무도 처리하지 않는 잡**이 남는다
어느 것도 예외를 띄우지 않으므로, 여기서 못 박지 않으면 라이브에서 사용자가 발견한다.

실제 Valkey·SQS·Vertex 를 부르지 않는다 — 전부 가짜로 갈아끼운다(비용 0).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "serverless", _ROOT / "ml" / "video-recipe"):
    sys.path.insert(0, str(_p))

from common import jobs  # noqa: E402


class FakeRedis:
    """`set(nx=, ex=)` · `get` · `delete` 만 흉내낸다 — jobs.py 가 쓰는 전부다."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)


class FakeSqs:
    def __init__(self, fail=False) -> None:
        self.sent: list[dict] = []
        self.fail = fail

    def send_message(self, QueueUrl, MessageBody):  # noqa: N803 — boto3 시그니처
        if self.fail:
            raise RuntimeError("queue down")
        self.sent.append({"url": QueueUrl, "body": json.loads(MessageBody)})
        return {"MessageId": "m1"}


@pytest.fixture
def wired(monkeypatch):
    """jobs 모듈의 커넥션을 가짜로 갈아끼운다."""
    r, q = FakeRedis(), FakeSqs()
    monkeypatch.setattr(jobs, "redis", lambda: r)
    monkeypatch.setattr(jobs, "sqs", lambda: q)
    return r, q


def _load(fn_dir: str, alias: str):
    """🔴 두 핸들러가 **둘 다 `app.py`** 라 그냥 `import app` 하면 먼저 로드된 쪽이 캐시되어
    다른 함수를 부른 줄도 모르고 테스트가 통과한다(실제로 그렇게 한 번 틀렸다).
    Lambda 는 함수마다 실행 환경이 갈려 문제가 없지만, 한 프로세스에서 둘을 다루는
    여기서는 **고유 이름으로 따로** 올려야 한다."""
    import importlib.util  # noqa: PLC0415

    if alias in sys.modules:
        return sys.modules[alias]
    spec = importlib.util.spec_from_file_location(
        alias, _ROOT / "serverless" / fn_dir / "app.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


def _api(monkeypatch, backend_ready=True):
    monkeypatch.setenv("VIDEO_GENAI_BACKEND", "vertex")
    monkeypatch.setenv("GCP_PROJECT_ID", "p" if backend_ready else "")
    monkeypatch.setenv("VIDEO_JOBS_QUEUE_URL", "https://sqs/q")
    api = _load("ai_video_api", "_mp_video_api")
    monkeypatch.setattr(api, "QUEUE_URL", "https://sqs/q")
    return api


def _post(url="https://www.youtube.com/watch?v=abc12345678"):
    return {"httpMethod": "POST", "path": "/api/recipes/extract",
            "body": json.dumps({"url": url}), "isBase64Encoded": False}


# ── 접수 ───────────────────────────────────────────────────────────────────────
def test_접수는_큐에_넣고_202를_준다(wired, monkeypatch):
    _r, q = wired
    api = _api(monkeypatch)
    res = api.handler(_post(), None)
    assert res["statusCode"] == 202
    body = json.loads(res["body"])
    assert body["status"] == "PENDING" and body["from_cache"] is False
    assert len(q.sent) == 1, "워커 큐로 보내지 않으면 아무도 처리하지 않는다"
    assert q.sent[0]["body"]["job_id"] == body["job_id"]


def test_캐시_히트면_큐를_안_탄다(wired, monkeypatch):
    """다른 유저가 이미 분석한 영상 — Gemini 도 워커도 안 부른다(비용 0)."""
    _r, q = wired
    api = _api(monkeypatch)
    norm = api._normalize("https://www.youtube.com/watch?v=abc12345678")
    jobs.set_cached(norm, {"title": "김치찌개", "is_recipe": True})

    res = api.handler(_post(), None)
    assert json.loads(res["body"])["from_cache"] is True
    assert q.sent == [], "캐시 히트인데 큐를 타면 비용이 두 배로 든다"


def test_같은_영상_동시요청은_409(wired, monkeypatch):
    api = _api(monkeypatch)
    assert api.handler(_post(), None)["statusCode"] == 202
    assert api.handler(_post(), None)["statusCode"] == 409


def test_큐_전송_실패는_락과_잡을_되돌린다(wired, monkeypatch):
    """🔴 되돌리지 않으면 **아무도 처리하지 않는 잡**이 남고 유저는 폴링만 계속한다."""
    r, _q = wired
    monkeypatch.setattr(jobs, "sqs", lambda: FakeSqs(fail=True))
    api = _api(monkeypatch)

    res = api.handler(_post(), None)
    assert res["statusCode"] == 503
    assert not [k for k in r.store if k.startswith("video:lock:")], "락이 남으면 재시도가 409 로 막힌다"


def test_유튜브가_아니면_400(wired, monkeypatch):
    api = _api(monkeypatch)
    assert api.handler(_post("https://example.com/x"), None)["statusCode"] == 400


def test_백엔드_미준비면_503(wired, monkeypatch):
    api = _api(monkeypatch, backend_ready=False)
    assert api.handler(_post(), None)["statusCode"] == 503


def test_폴링은_잡_상태를_돌려준다(wired, monkeypatch):
    api = _api(monkeypatch)
    job_id = json.loads(api.handler(_post(), None)["body"])["job_id"]
    res = api.handler({"httpMethod": "GET",
                       "path": f"/api/recipes/extract/{job_id}"}, None)
    assert res["statusCode"] == 200
    assert json.loads(res["body"])["status"] == "PENDING"


def test_없는_잡은_404(wired, monkeypatch):
    api = _api(monkeypatch)
    res = api.handler({"httpMethod": "GET", "path": "/api/recipes/extract/nope"}, None)
    assert res["statusCode"] == 404


def test_ALB_응답에_statusCode가_있다(wired, monkeypatch):
    """🔴 없으면 대상그룹이 응답을 못 읽어 **전부 502** 가 된다(API Gateway 와 형식이 다르다)."""
    api = _api(monkeypatch)
    for res in (api.handler(_post(), None),
                api.handler({"httpMethod": "GET", "path": "/api/recipes/extract/x"}, None)):
        assert "statusCode" in res and "body" in res
        json.loads(res["body"])          # 본문은 항상 JSON 문자열이어야 한다


# ── 워커 ───────────────────────────────────────────────────────────────────────
def _sqs_event(body: dict, received: int = 1):
    return {"Records": [{"body": json.dumps(body),
                         "attributes": {"ApproximateReceiveCount": str(received)}}]}


def _worker():
    return _load("ai_video_worker", "_mp_video_worker")


def test_중복_전달은_캐시로_끝난다(wired, monkeypatch):
    """🔴 SQS 표준 큐는 최소 1회 전달 — 같은 메시지가 두 번 올 수 있다(V-03).

    워커 진입부에서 캐시를 다시 보지 않으면 두 번째 전달이 **Gemini 를 또 부른다**.
    """
    wk = _worker()
    jobs.set_cached("n1", {"title": "김치찌개"})
    out = wk.handler(_sqs_event({"job_id": "j1", "url": "u", "norm": "n1"}), None)
    assert out["results"][0]["from_cache"] is True
    assert jobs.get_job("j1")["status"] == "DONE"


def test_마지막_시도는_FAILED를_남긴다(wired, monkeypatch):
    """🔴 안 남기면 DLQ 로 가는 동안 잡이 PENDING 이라 **유저가 영원히 기다린다**(§3③)."""
    wk = _worker()
    monkeypatch.setattr(wk, "_process", lambda body: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setenv("MAX_RECEIVE_COUNT", "3")

    out = wk.handler(_sqs_event({"job_id": "j2", "url": "u", "norm": "n2"}, received=3), None)
    assert out["results"][0]["status"] == "FAILED"
    assert jobs.get_job("j2")["status"] == "FAILED"


def test_재시도가_남았으면_예외를_올린다(wired, monkeypatch):
    """🔴 삼키면 SQS 가 성공으로 알고 메시지를 지운다 — 잡이 PENDING 에 영영 남는다."""
    wk = _worker()
    monkeypatch.setattr(wk, "_process", lambda body: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setenv("MAX_RECEIVE_COUNT", "3")

    with pytest.raises(RuntimeError):
        wk.handler(_sqs_event({"job_id": "j3", "url": "u", "norm": "n3"}, received=1), None)
    assert jobs.get_job("j3") is None, "아직 실패로 마감하면 안 된다 — 재시도가 남았다"


def test_잘못된_메시지는_조용히_버린다(wired):
    """우리가 만든 모양이 아니면 재시도해도 같다 — DLQ 로 보낼 이유가 없다."""
    wk = _worker()
    out = wk.handler(_sqs_event({"nope": 1}), None)
    assert out["results"][0]["skipped"] == "bad_message"


# ── 접수·워커가 같은 계약을 쓰는가 ─────────────────────────────────────────────
def test_락_TTL이_워커_타임아웃보다_길다():
    """🔴 뒤집히면 "락은 풀렸는데 워커는 아직 도는" 구간이 생겨 같은 URL 이 중복 분석된다(§3①)."""
    wk = _worker()
    assert wk.EXTRACT_TIMEOUT_S < jobs.LOCK_TTL_S, (
        f"워커 타임아웃 {wk.EXTRACT_TIMEOUT_S}s 가 락 TTL {jobs.LOCK_TTL_S}s 이상이다 — 중복 분석"
    )


def test_접수와_워커가_같은_캐시_키를_쓴다(wired, monkeypatch):
    """접수가 잡은 키와 워커가 보는 키가 갈리면 캐시가 통째로 무의미해진다."""
    _r, q = wired
    api = _api(monkeypatch)
    api.handler(_post(), None)
    norm_sent = q.sent[0]["body"]["norm"]
    assert norm_sent == api._normalize("https://www.youtube.com/watch?v=abc12345678")
    # 워커는 메시지의 norm 을 그대로 캐시 키로 쓴다 — 위 test_중복_전달 이 그 경로를 탄다
    jobs.set_cached(norm_sent, {"title": "x"})
    assert jobs.get_cached(norm_sent) is not None
