"""스모크 스크립트의 **판정 로직**을 태운다. AWS 를 안 부른다(가짜 클라이언트).

🔴 **왜 스모크 스크립트에 테스트가 필요한가** — 이 스크립트가 틀리면 «전부 ✅» 를 찍고,
   그러면 우리는 깨진 배포를 정상으로 믿는다. 검사기가 조용히 틀리는 것이 검사기가 없는
   것보다 나쁘다. 그래서 **실패를 만들어 보고 실제로 🔴 가 나오는지** 확인한다.

여기서 못 박는 세 가지는 전부 «성공처럼 보이는 실패» 다:
  · Lambda 는 함수가 죽어도 **HTTP 200** 을 준다 — 실패는 `FunctionError` 에만 있다
  · ALB 응답에 `statusCode` 가 없으면 ALB 가 502 를 주는데 **함수는 성공**으로 끝난다
  · 배치를 `apply=true` 로 부르면 «미리보기» 라고 믿는 채로 **실제 적재**가 일어난다
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location("_smoke", _ROOT / "serverless" / "smoke.py")
smoke = importlib.util.module_from_spec(spec)
sys.modules["_smoke"] = smoke
spec.loader.exec_module(smoke)


class FakeClient:
    """`invoke` · `get_function` 만 흉내낸다 — 스크립트가 쓰는 전부다."""

    def __init__(self, *, body=None, function_error=None, arch="arm64", raises=None):
        self.body, self.function_error, self.arch, self.raises = body, function_error, arch, raises
        self.calls: list[dict] = []

    def invoke(self, FunctionName, InvocationType, Payload):  # noqa: N803 — boto3 시그니처
        if self.raises:
            raise self.raises
        self.calls.append({"name": FunctionName, "payload": json.loads(Payload)})
        out = {"Payload": io.BytesIO((self.body or "").encode())}
        if self.function_error:
            out["FunctionError"] = self.function_error
        return out

    def get_function(self, FunctionName):  # noqa: N803
        if self.raises:
            raise self.raises
        return {"Configuration": {"Architectures": [self.arch]}}


ALB_OK = json.dumps({"statusCode": 200, "body": '{"status":"ok"}'})


# ── ALB 판정 ─────────────────────────────────────────────────────────────────
def test_ALB_이벤트에_elb_키가_들어간다():
    """🔴 이게 없으면 Mangum 도 `common/alb.py` 도 ALB 로 못 알아본다.
    콘솔 Test 버튼의 기본 payload 로는 재현이 안 되는 자리다."""
    ev = smoke.alb_event("GET", "/health")
    assert ev["requestContext"]["elb"]["targetGroupArn"]
    assert ev["httpMethod"] == "GET" and ev["path"] == "/health"
    assert ev["isBase64Encoded"] is False


def test_기대한_상태코드면_통과():
    c = FakeClient(body=ALB_OK)
    mark, detail = smoke.check(c, "chat-api", smoke.FUNCTIONS["chat-api"], write=False)
    assert mark == "✅" and "statusCode=200" in detail


def test_statusCode_가_없으면_잡는다():
    """🔴 함수는 «성공» 으로 끝나는데 ALB 는 502 를 준다. 로그만 봐서는 안 보인다."""
    c = FakeClient(body=json.dumps({"body": "ok"}))
    mark, detail = smoke.check(c, "chat-api", smoke.FUNCTIONS["chat-api"], write=False)
    assert mark == "🔴" and "statusCode 가 없다" in detail


def test_상태코드가_다르면_잡는다():
    c = FakeClient(body=json.dumps({"statusCode": 500, "body": "boom"}))
    mark, detail = smoke.check(c, "chat-api", smoke.FUNCTIONS["chat-api"], write=False)
    assert mark == "🔴" and "기대=200" in detail


def test_JSON_이_아니면_잡는다():
    c = FakeClient(body="<html>502</html>")
    mark, _ = smoke.check(c, "chat-api", smoke.FUNCTIONS["chat-api"], write=False)
    assert mark == "🔴"


# ── 조용한 실패 ──────────────────────────────────────────────────────────────
def test_FunctionError_를_성공으로_읽지_않는다():
    """🔴 Lambda 는 **함수가 죽어도 HTTP 200** 을 준다. 실패는 이 헤더에만 있다 —
    안 보면 `ModuleNotFoundError` 로 죽은 함수를 정상으로 센다."""
    c = FakeClient(function_error="Unhandled", body=json.dumps({
        "errorType": "ModuleNotFoundError",
        "errorMessage": "No module named 'app.vendor.quantity'"}))
    mark, detail = smoke.check(c, "chat-api", smoke.FUNCTIONS["chat-api"], write=False)
    assert mark == "🔴"
    assert "ModuleNotFoundError" in detail and "app.vendor.quantity" in detail


def test_호출_자체가_실패해도_던지지_않는다():
    """한 함수가 없다고 나머지 검사가 멈추면 안 된다."""
    c = FakeClient(raises=RuntimeError("ResourceNotFound"))
    mark, detail = smoke.check(c, "chat-api", smoke.FUNCTIONS["chat-api"], write=False)
    assert mark == "🔴" and "RuntimeError" in detail


# ── 배치: 미리보기가 기본 ────────────────────────────────────────────────────
def test_배치는_기본이_미리보기다():
    """🔴 기본이 `apply=true` 면 «확인해 봤다» 가 곧 **실제 적재**가 된다.
    식품안전 배치라 이 사고는 실제로 위험하다."""
    c = FakeClient(body=json.dumps({"scanned": 1}))
    mark, detail = smoke.check(c, "shelflife-draft", smoke.FUNCTIONS["shelflife-draft"],
                               write=False)
    assert mark == "✅"
    assert c.calls[0]["payload"]["apply"] is False
    assert "apply=False" in detail          # 🔵 결과에 남긴다 — CloudTrail 은 payload 를 안 남긴다


def test_write_를_줘야_실제로_적재한다():
    c = FakeClient(body=json.dumps({"inserted": 3}))
    smoke.check(c, "shelflife-draft", smoke.FUNCTIONS["shelflife-draft"], write=True)
    assert c.calls[0]["payload"]["apply"] is True


def test_모든_배치의_기본_payload_가_미리보기다():
    """카탈로그를 늘릴 때 `apply` 를 빼먹으면 여기서 걸린다."""
    for name, spec_ in smoke.FUNCTIONS.items():
        if spec_["kind"] == "batch":
            assert spec_["payload"].get("apply") is False, f"{name}: 기본이 미리보기가 아니다"


# ── 워커: 직접 부르지 않는다 ─────────────────────────────────────────────────
def test_워커는_직접_호출하지_않고_아키텍처만_본다():
    """🔵 워커는 큐가 깨우는 것이다. 손으로 부르면 **큐 배선이 틀렸는데 워커는 멀쩡한**
    상태를 통과시킨다 — 검사가 거짓 안심을 준다."""
    c = FakeClient(arch="arm64")
    mark, detail = smoke.check(c, "ocr-worker", smoke.FUNCTIONS["ocr-worker"], write=False)
    assert mark == "✅" and "arm64" in detail
    assert not c.calls, "워커를 직접 불렀다"


def test_x86_로_올라갔으면_잡는다():
    """🔴 번들 휠이 aarch64 라 x86 함수는 **첫 호출에서** invalid ELF header 로 죽는다(C-29)."""
    c = FakeClient(arch="x86_64")
    mark, detail = smoke.check(c, "video-worker", smoke.FUNCTIONS["video-worker"], write=False)
    assert mark == "🔴" and "x86_64" in detail


# ── 카탈로그가 실물과 맞는가 ─────────────────────────────────────────────────
def test_카탈로그가_serverless_디렉터리와_일치한다():
    """🔴 함수를 추가하고 스모크에 안 넣으면 **그 함수만 아무도 안 본다.**"""
    dirs = {p.name.replace("ai_", "").replace("_", "-")
            for p in (_ROOT / "serverless").iterdir()
            if p.is_dir() and p.name.startswith("ai_")}
    assert dirs == set(smoke.FUNCTIONS), (
        f"스모크 카탈로그와 함수 디렉터리가 다르다 — "
        f"빠짐 {dirs - set(smoke.FUNCTIONS)} · 잉여 {set(smoke.FUNCTIONS) - dirs}")


@pytest.mark.parametrize("name", list(smoke.FUNCTIONS))
def test_함수마다_검사_방식이_정해져_있다(name):
    assert smoke.FUNCTIONS[name]["kind"] in ("batch", "alb", "sqs")
