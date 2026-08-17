"""OCR 접수·워커 분할의 계약 검증. `test_video_split.py` 와 같은 목적이고 **다른 위험**을 본다.

video 와 갈리는 지점이 셋이다 — 여기서 못 박지 않으면 전부 조용히 틀린다:
  · **키 네임스페이스** — `JOB_NS` 를 안 걸면 OCR 이 `video:job:*` 에 쓴다. 에러가 아니라
    폴링 404 로 보여서 원인을 한참 못 찾는다.
  · **락이 없다** — video 는 URL 로 단일비행을 잡지만 OCR 은 잡을 대상이 없다.
    중복 전달 방어를 **잡 상태**로 하므로, 그게 실제로 도는지 봐야 한다.
  · **이미지가 ALB 를 못 지난다** — 요청 본문 상한 1MB(AWS 고정). 큰 사진은 반드시
    presigned 경로로 가야 하고, 접수는 그걸 **안내**해야 한다(그냥 413 이면 유저가 막힌다).

실제 Valkey·SQS·S3·Gemini 를 부르지 않는다 — 전부 가짜로 갈아끼운다(비용 0).
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "serverless",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common import jobs  # noqa: E402


class FakeRedis:
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


class FakeS3:
    """boto3 S3 클라이언트 중 이 두 함수가 쓰는 것만."""

    def __init__(self, objects=None) -> None:
        self.objects: dict[tuple[str, str], bytes] = dict(objects or {})
        self.deleted: list[tuple[str, str]] = []

    def generate_presigned_url(self, op, Params, ExpiresIn):  # noqa: N803
        return f"https://s3.example/{Params['Bucket']}/{Params['Key']}?exp={ExpiresIn}"

    def head_object(self, Bucket, Key):  # noqa: N803
        if (Bucket, Key) not in self.objects:
            raise RuntimeError("404")
        return {"ContentLength": len(self.objects[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body):  # noqa: N803
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):  # noqa: N803
        import io  # noqa: PLC0415

        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket, Key):  # noqa: N803
        self.deleted.append((Bucket, Key))
        self.objects.pop((Bucket, Key), None)


BUCKET = "mp-ai-uploads"


@pytest.fixture
def wired(monkeypatch):
    """jobs 의 커넥션과 **네임스페이스**를 갈아끼운다.

    🔴 `jobs.NS` 는 모듈 로드 시점에 `JOB_NS` 로 정해진다. 테스트가 env 를 나중에 바꿔도
       이미 굳어 있으므로 **모듈 속성을 직접** 바꾼다. (Lambda 에서는 함수마다 env 가
       고정이라 이 문제가 없다.)
    """
    r, q = FakeRedis(), FakeSqs()
    monkeypatch.setattr(jobs, "redis", lambda: r)
    monkeypatch.setattr(jobs, "sqs", lambda: q)
    monkeypatch.setattr(jobs, "NS", "ocr")
    return r, q


def _load(fn_dir: str, filename: str, alias: str):
    """🔴 함수마다 진입점 파일 이름이 달라도(`app.py`/`handler.py`) **고유 이름으로 따로** 올린다.
    그냥 import 하면 먼저 로드된 쪽이 캐시돼 다른 함수를 부른 줄도 모르고 통과한다
    (video 테스트에서 실제로 그렇게 한 번 틀렸다)."""
    import importlib.util  # noqa: PLC0415

    if alias in sys.modules:
        return sys.modules[alias]
    spec = importlib.util.spec_from_file_location(
        alias, _ROOT / "serverless" / fn_dir / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


def _api(monkeypatch, s3=None):
    monkeypatch.setenv("JOB_NS", "ocr")
    monkeypatch.setenv("OCR_UPLOAD_BUCKET", BUCKET)
    monkeypatch.setenv("OCR_JOBS_QUEUE_URL", "https://sqs/ocr")
    mod = _load("ai_ocr_api", "app.py", "_ocr_api")
    mod.BUCKET, mod.QUEUE_URL = BUCKET, "https://sqs/ocr"
    fake = s3 or FakeS3()
    monkeypatch.setattr(mod, "s3", lambda: fake)
    return mod, fake


def _worker(monkeypatch, s3=None):
    monkeypatch.setenv("JOB_NS", "ocr")
    mod = _load("ai_ocr_worker", "handler.py", "_ocr_worker")
    fake = s3 or FakeS3()
    monkeypatch.setattr(mod, "s3", lambda: fake)
    return mod, fake


def _alb(method, path, *, body="", b64=False):
    return {"requestContext": {"elb": {"targetGroupArn": "arn:x"}},
            "httpMethod": method, "path": path, "queryStringParameters": {},
            "headers": {"host": "aws.mealbong.cloud"},
            "body": body, "isBase64Encoded": b64}


def _sqs_event(body: dict, received: int = 1):
    return {"Records": [{"body": json.dumps(body),
                         "attributes": {"ApproximateReceiveCount": str(received)}}]}


# ── 키 네임스페이스 ──────────────────────────────────────────────────────────
def test_ocr_잡은_ocr_키에_들어간다(wired, monkeypatch):
    """🔴 `services/ocr/app/store.py` 의 `ocr:job:{}` 와 **같은 키**여야 한다.
    갈리면 파드가 접수하고 Lambda 가 폴링하는 국면에서 잡을 못 찾는다(404 로만 보인다)."""
    r, _ = wired
    api, s3 = _api(monkeypatch)
    resp = api.handler(_alb("POST", "/api/pantry/ocr",
                            body=base64.b64encode(b"\xff\xd8jpeg").decode(), b64=True), None)
    job_id = json.loads(resp["body"])["job_id"]
    assert f"mp-ai:ocr:job:{job_id}" in r.store, f"실제 키: {list(r.store)}"
    assert not any(k.startswith(("video:", "mp-ai:video:")) for k in r.store)


def test_모든_키에_mp_ai_접두사가_붙는다(wired):
    """🔴 **ElastiCache 가 앱과 공유**다(2026-08-17). 접두사가 유일한 격리이고, 빠지면
    파드가 만든 잡을 우리가 덮거나 그 반대가 된다 — 그 사고는 «가끔 잡이 사라진다» 로
    나타나서 원인을 짚기 어렵다.
    🔵 정본도 같은 방향이다 — «옆에 독립적으로 세우는 프로젝트»(mp_aws_team_access §4)."""
    jobs.put_job("j0", {"status": "PENDING"})
    keys = list(wired[0].store)
    assert keys and all(k.startswith("mp-ai:") for k in keys), keys


def test_ocr_네임스페이스에는_락이_없어서_부르면_터진다(wired):
    """락은 **없는 게 맞다**(같은 사진을 두 번 올릴 이유가 없다). 그래서 no-op 이 아니라
    즉시 실패여야 한다 — no-op 이면 «락을 잡았다» 고 믿는 코드가 그대로 흘러간다."""
    with pytest.raises(RuntimeError, match="lock"):
        jobs.acquire("아무거나")


# ── ALB 1MB 상한 ─────────────────────────────────────────────────────────────
def test_큰_사진은_막되_다음_수단을_알려준다(wired, monkeypatch):
    """🔴 ALB → Lambda 요청 본문 상한은 **1MB 고정**이라 8MB 사진은 함수에 닿지도 못한다.
    그냥 «용량 초과» 로 끝내면 유저는 막힌 채로 남는다 — presigned 경로를 안내해야 한다."""
    api, _ = _api(monkeypatch)
    big = base64.b64encode(b"x" * (api.INLINE_MAX_BYTES + 1)).decode()
    resp = api.handler(_alb("POST", "/api/pantry/ocr", body=big, b64=True), None)
    assert resp["statusCode"] == 413
    assert "upload-url" in json.loads(resp["body"])["detail"]


def test_presigned_URL_은_job_id_를_서버가_짓는다(wired, monkeypatch):
    """클라이언트가 job_id 를 짓게 하면 남의 잡을 덮어쓸 수 있다."""
    api, _ = _api(monkeypatch)
    resp = api.handler(_alb("POST", "/api/pantry/ocr/upload-url",
                            body=json.dumps({"job_id": "남의잡"})), None)
    got = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert got["job_id"] != "남의잡" and len(got["job_id"]) == 32
    assert got["job_id"] in got["upload_url"]


def test_안_올라온_객체는_접수하지_않는다(wired, monkeypatch):
    """presigned 를 받고 업로드에 실패한 채 접수하면, 큐에 «없는 객체» 가 흘러가
    워커가 실패해야만 유저가 알게 된다. 접수에서 끊는다."""
    api, _ = _api(monkeypatch)
    resp = api.handler(_alb("POST", "/api/pantry/ocr",
                            body=json.dumps({"job_id": "없는잡"})), None)
    assert resp["statusCode"] == 400


def test_업로드된_객체면_접수하고_큐에_좌표만_싣는다(wired, monkeypatch):
    """🔵 SQS 본문 상한은 256KB — 이미지를 실을 수 없다. 좌표(bucket/key)만 흐른다."""
    _, q = wired
    s3 = FakeS3({(BUCKET, "receipts/abc"): b"\xff\xd8jpeg"})
    api, _ = _api(monkeypatch, s3)
    resp = api.handler(_alb("POST", "/api/pantry/ocr",
                            body=json.dumps({"job_id": "abc"})), None)
    assert resp["statusCode"] == 202
    assert q.sent[0]["body"] == {"job_id": "abc", "bucket": BUCKET, "key": "receipts/abc"}


def test_큐_전송이_실패하면_PENDING_을_남기지_않는다(wired, monkeypatch):
    """🔴 PENDING 을 남기면 **아무도 처리하지 않는 잡**이 되고 유저는 폴링만 계속한다."""
    r, q = wired
    q.fail = True
    api, _ = _api(monkeypatch)
    resp = api.handler(_alb("POST", "/api/pantry/ocr",
                            body=base64.b64encode(b"\xff\xd8").decode(), b64=True), None)
    assert resp["statusCode"] == 503
    saved = [json.loads(v) for k, v in r.store.items() if k.startswith("mp-ai:ocr:job:")]
    assert saved and all(s["status"] == "FAILED" for s in saved)


def test_폴링은_워커가_넣은_JSON_을_그대로_돌려준다(wired, monkeypatch):
    """모양을 여기서 다시 만들면 워커와 두 벌이 갈린다 — 프론트가 조용히 빈 값을 그린다."""
    api, _ = _api(monkeypatch)
    jobs.put_job("j1", {"status": "DONE", "store": "이마트", "items": [{"name": "무"}]})
    resp = api.handler(_alb("GET", "/api/pantry/ocr/j1"), None)
    assert json.loads(resp["body"])["store"] == "이마트"
    assert api.handler(_alb("GET", "/api/pantry/ocr/없음"), None)["statusCode"] == 404


# ── 워커 ─────────────────────────────────────────────────────────────────────
def test_중복_전달이면_유료모델을_안_부른다(wired, monkeypatch):
    """🔴 락이 없으므로 방어는 **잡 상태**뿐이다. 이게 없으면 SQS 중복 전달 한 번이
    곧 Gemini Vision 호출 한 번(=돈)이다."""
    worker, s3 = _worker(monkeypatch)
    jobs.put_job("j2", {"status": "DONE", "store": "이마트"})
    called = []
    monkeypatch.setattr(s3, "get_object",
                        lambda **k: called.append(k) or {"Body": None})
    out = worker.handler(_sqs_event({"job_id": "j2", "bucket": BUCKET, "key": "receipts/j2"}), None)
    assert out["results"][0]["duplicate"] is True
    assert not called, "이미 끝난 잡인데 S3 를 읽었다 — 모델도 불렀을 것이다"


def test_잘못된_메시지는_DLQ_로_안_보낸다(wired, monkeypatch):
    """재시도해도 같은 결과다. 예외를 올리면 재시도만 태우고 DLQ 를 오염시킨다."""
    worker, _ = _worker(monkeypatch)
    out = worker.handler(_sqs_event({"job_id": "x"}), None)      # bucket/key 없음
    assert out["results"][0] == {"skipped": "bad_message"}


def test_마지막_시도면_FAILED_를_남기고_원본을_지운다(wired, monkeypatch):
    """🔴 안 남기면 DLQ 로 가는 동안 잡이 PENDING 이라 **유저가 영원히 기다린다.**"""
    r, _ = wired
    s3 = FakeS3({(BUCKET, "receipts/j3"): b"\xff\xd8"})
    worker, _ = _worker(monkeypatch, s3)
    monkeypatch.setattr(worker, "_process", lambda body: (_ for _ in ()).throw(TimeoutError()))
    out = worker.handler(_sqs_event({"job_id": "j3", "bucket": BUCKET, "key": "receipts/j3"},
                                    received=3), None)
    assert out["results"][0]["status"] == "FAILED"
    saved = json.loads(r.store["mp-ai:ocr:job:j3"])
    assert saved["status"] == "FAILED" and "시간 초과" in saved["reason"]
    assert (BUCKET, "receipts/j3") in s3.deleted, "더 시도 안 하는데 영수증 원본이 남았다"


def test_재시도가_남았으면_예외를_올리고_원본을_남긴다(wired, monkeypatch):
    """🔴 삼키면 SQS 가 성공으로 알고 메시지를 지운다 — 잡이 PENDING 에 영영 남는다.
    🔵 원본을 지우면 재시도가 읽을 것이 없다."""
    s3 = FakeS3({(BUCKET, "receipts/j4"): b"\xff\xd8"})
    worker, _ = _worker(monkeypatch, s3)
    monkeypatch.setattr(worker, "_process", lambda body: (_ for _ in ()).throw(RuntimeError("네트워크")))
    with pytest.raises(RuntimeError):
        worker.handler(_sqs_event({"job_id": "j4", "bucket": BUCKET, "key": "receipts/j4"},
                                  received=1), None)
    assert (BUCKET, "receipts/j4") not in s3.deleted


def test_성공_경로가_끝까지_돌고_원본을_지운다(wired, monkeypatch):
    """🔵 여기만 **파이프라인을 실제로 태운다** — `OCR_BACKEND=mock`(그 용도로 만든 백엔드)
    이라 유료 API 도 키도 필요 없다. 그래서 이 하나가 확인하는 것이 넓다:
      · `app.pipeline.process` 를 import 할 수 있는가 (번들 의존성의 최소 집합)
      · `_done_payload` 가 현행 `_run_job` 과 **같은 키**를 내는가 (프론트가 읽는 모양)
      · 개인정보인 영수증 원본이 성공 후 지워지는가
    """
    monkeypatch.setenv("OCR_BACKEND", "mock")
    s3 = FakeS3({(BUCKET, "receipts/j5"): b"\xff\xd8"})
    worker, _ = _worker(monkeypatch, s3)
    from app.config import settings  # noqa: PLC0415
    monkeypatch.setattr(settings, "ocr_backend", "mock")

    out = worker.handler(_sqs_event({"job_id": "j5", "bucket": BUCKET, "key": "receipts/j5"}), None)
    assert out["results"][0]["status"] == "DONE"
    assert out["results"][0]["items"] > 0, "mock 영수증은 품목이 있어야 한다"
    assert (BUCKET, "receipts/j5") in s3.deleted

    saved = json.loads(wired[0].store["mp-ai:ocr:job:j5"])
    # 🔴 현행 `_run_job` 의 DONE 본문과 키가 같아야 한다 — 하나만 달라도 프론트가 조용히 빈다.
    assert set(saved) >= {"status", "store", "purchased_at", "total_amount", "backend", "items"}
    assert set(saved["items"][0]) >= {"raw_text", "name", "item_id", "quantity", "price",
                                      "is_food", "category", "storage", "in_expense",
                                      "needs_review", "confirmed"}
