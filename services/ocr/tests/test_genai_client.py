"""Gemini 클라이언트 팩토리 — 백엔드 토글 계약(실제 호출 없음).

Vertex 전환은 **되돌아올 수 있어야** 한다(env 하나로 롤백). 그리고 설정 누락이
**조용히 기본값으로 넘어가면 안 된다** — 특히 리전은 데이터 레지던시를 결정한다.
"""
import pytest

from app.pipeline.backend.genai_client import GenaiConfigError, make_client


def test_unknown_backend_rejected():
    with pytest.raises(GenaiConfigError, match="알 수 없는 backend"):
        make_client("gemini-pro")


def test_api_key_backend_requires_key():
    with pytest.raises(GenaiConfigError, match="GEMINI_API_KEY"):
        make_client("api_key", api_key="")


def test_vertex_requires_project():
    with pytest.raises(GenaiConfigError, match="GCP_PROJECT_ID"):
        make_client("vertex", project="", location="asia-northeast3")


def test_vertex_requires_explicit_location():
    """리전 기본값을 두지 않는다 — 영수증은 개인정보라 조용히 글로벌로 붙으면 안 된다."""
    with pytest.raises(GenaiConfigError, match="GCP_LOCATION"):
        make_client("vertex", project="my-project", location="")


def test_error_message_guides_the_fix():
    """설정 오류는 '무엇을 어떻게 고치는지'까지 말해야 한다 — 배포 중 진단 시간을 줄인다."""
    with pytest.raises(GenaiConfigError) as e:
        make_client("vertex", project="", location="us-central1")
    assert "gcloud config set project" in str(e.value)


# ── 서비스 계정 JSON 원문 경로 (K8s 배선) ──────────────────────────────────────
# `envFrom: secretRef` 로 이미 시크릿이 들어오는 구조라, 키를 파일이 아닌 env 로 받는다.
# 파일 마운트를 쓰면 볼륨·defaultMode·Deployment 수정이 필요한데 그 매니페스트는 별도
# GitOps 저장소에 있다(접근 불가). env 경로는 ExternalSecret 한 줄만 늘리면 된다.

def test_sa_key_json_rejects_non_json():
    with pytest.raises(GenaiConfigError, match="GCP_SA_KEY_JSON 파싱 실패"):
        make_client("vertex", project="p", location="global", sa_key_json="/path/to/key.json")


def test_sa_key_json_rejects_wrong_shape():
    """JSON 이긴 한데 서비스 계정 키가 아닌 경우 — 형식 오류로 구분해서 알려준다."""
    with pytest.raises(GenaiConfigError, match="서비스 계정 키 형식이 아니다"):
        make_client("vertex", project="p", location="global", sa_key_json='{"hello": "world"}')


def test_sa_key_json_never_leaks_into_error_message():
    """🔴 키가 예외 메시지로 새면 그대로 로그에 박힌다 — 가장 흔한 유출 경로다."""
    secret = '{"type":"service_account","private_key":"SUPER-SECRET-MATERIAL"}'
    with pytest.raises(GenaiConfigError) as e:
        make_client("vertex", project="p", location="global", sa_key_json=secret)
    assert "SUPER-SECRET-MATERIAL" not in str(e.value)
    assert "SUPER-SECRET-MATERIAL" not in repr(e.value)


def test_empty_sa_key_json_keeps_adc_path(monkeypatch):
    """비우면 종전 ADC 자동탐색 그대로 — 로컬·CI 가 깨지지 않아야 한다(하위호환)."""
    captured = {}

    class _FakeClient:
        def __init__(self, **kw):
            captured.update(kw)

    import google.genai as genai
    monkeypatch.setattr(genai, "Client", _FakeClient)
    make_client("vertex", project="p", location="global", sa_key_json="")
    assert captured["credentials"] is None      # ADC 에 맡긴다
    assert captured["vertexai"] is True
