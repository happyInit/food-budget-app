from __future__ import annotations

import pytest

from app.chat_contract import (
    ChatProviderError,
    ChatRequest,
    build_bedrock_chat_response,
    build_mock_chat_response,
)


class _FakeBedrockClient:
    def __init__(self, response: dict) -> None:
        self._response = response
        self.last_call: dict | None = None

    def converse(self, **kwargs):
        self.last_call = kwargs
        return self._response


def _text_response(text: str) -> dict:
    return {"output": {"message": {"content": [{"text": text}]}}}


def test_mock_chat_response_labels_itself_as_mock_and_echoes_the_question():
    request = ChatRequest(question="지금 서버 상태 어때?")
    response = build_mock_chat_response(request)
    assert response.provider == "mock"
    assert "서버 상태" in response.answer


def test_bedrock_chat_response_returns_model_text():
    client = _FakeBedrockClient(_text_response("정상입니다. CPU 사용률 12%, 에러 로그 없음."))
    request = ChatRequest(question="지금 서버 상태 어때?", snapshot={"active_anomaly_count": 0})
    response = build_bedrock_chat_response(
        request, region_name="ap-northeast-2", model_id="test-model", client=client
    )
    assert response.provider == "bedrock"
    assert response.answer == "정상입니다. CPU 사용률 12%, 에러 로그 없음."
    assert client.last_call["modelId"] == "test-model"
    # No forced tool use — chat answers are plain text, unlike RCA's structured draft.
    assert "toolConfig" not in client.last_call


def test_bedrock_chat_response_includes_the_snapshot_in_the_prompt():
    client = _FakeBedrockClient(_text_response("없습니다"))
    request = ChatRequest(question="에러로그 있어?", snapshot={"logs": {"error_or_warn_log_count": 0}})
    build_bedrock_chat_response(request, region_name="ap-northeast-2", model_id="test-model", client=client)
    sent_text = client.last_call["messages"][0]["content"][0]["text"]
    assert "error_or_warn_log_count" in sent_text
    assert "에러로그 있어?" in sent_text


def test_bedrock_chat_response_raises_when_client_call_fails():
    class _RaisingClient:
        def converse(self, **kwargs):
            raise RuntimeError("network unreachable")

    request = ChatRequest(question="상태 어때?")
    with pytest.raises(ChatProviderError):
        build_bedrock_chat_response(
            request, region_name="ap-northeast-2", model_id="test-model", client=_RaisingClient()
        )


def test_bedrock_chat_response_raises_when_response_has_no_text():
    client = _FakeBedrockClient({"output": {"message": {"content": []}}})
    request = ChatRequest(question="상태 어때?")
    with pytest.raises(ChatProviderError):
        build_bedrock_chat_response(
            request, region_name="ap-northeast-2", model_id="test-model", client=client
        )


def test_bedrock_chat_response_omits_guardrail_config_when_unset():
    client = _FakeBedrockClient(_text_response("정상입니다"))
    request = ChatRequest(question="상태 어때?")
    build_bedrock_chat_response(request, region_name="ap-northeast-2", model_id="test-model", client=client)
    assert "guardrailConfig" not in client.last_call


def test_bedrock_chat_response_applies_guardrail_config_when_both_id_and_version_set():
    client = _FakeBedrockClient(_text_response("정상입니다"))
    request = ChatRequest(question="상태 어때?")
    build_bedrock_chat_response(
        request,
        region_name="ap-northeast-2",
        model_id="test-model",
        guardrail_id="gid-123",
        guardrail_version="1",
        client=client,
    )
    assert client.last_call["guardrailConfig"] == {
        "guardrailIdentifier": "gid-123",
        "guardrailVersion": "1",
        "trace": "enabled",
    }


def test_bedrock_chat_response_omits_guardrail_config_when_only_id_set():
    """Both-or-neither — a lone id without a version is treated as unset, not a partial config."""
    client = _FakeBedrockClient(_text_response("정상입니다"))
    request = ChatRequest(question="상태 어때?")
    build_bedrock_chat_response(
        request,
        region_name="ap-northeast-2",
        model_id="test-model",
        guardrail_id="gid-123",
        client=client,
    )
    assert "guardrailConfig" not in client.last_call


def test_bedrock_chat_response_flags_guardrail_intervention():
    response = _text_response("The response could not be grounded and was blocked.")
    response["stopReason"] = "guardrail_intervened"
    client = _FakeBedrockClient(response)
    request = ChatRequest(question="상태 어때?")
    result = build_bedrock_chat_response(
        request,
        region_name="ap-northeast-2",
        model_id="test-model",
        guardrail_id="gid-123",
        guardrail_version="1",
        client=client,
    )
    assert result.guardrail_intervened is True


def test_bedrock_chat_response_guardrail_intervened_defaults_false():
    client = _FakeBedrockClient(_text_response("정상입니다"))
    request = ChatRequest(question="상태 어때?")
    result = build_bedrock_chat_response(
        request, region_name="ap-northeast-2", model_id="test-model", client=client
    )
    assert result.guardrail_intervened is False
