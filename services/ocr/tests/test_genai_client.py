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
