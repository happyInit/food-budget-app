from __future__ import annotations

import pytest

from app.rca_contract import BedrockRcaError, RcaAnalysisRequest, build_bedrock_rca
from tests.test_rca_prompt import _evidence


class FakeBedrockClient:
    def __init__(self, response: dict | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.kwargs: dict | None = None

    def converse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def _tool_response(tool_input: dict) -> dict:
    return {
        "output": {
            "message": {
                "content": [
                    {"toolUse": {"name": "submit_rca_draft", "input": tool_input}}
                ]
            }
        }
    }


def _valid_tool_input() -> dict:
    return {
        "causes": [
            {
                "rank": 1,
                "summary": "Recipe latency may be elevated.",
                "confidence": "low",
                "analysis": "p95 latency exceeded baseline; insufficient evidence to confirm root cause.",
                "evidence": [
                    {
                        "source": "alert",
                        "reference_id": "recipe-latency",
                        "summary": "Latency alert is firing.",
                    }
                ],
            }
        ],
        "propagation_path": [
            {"service": "recipe", "observation": "Alert correlation scope."}
        ],
        "checks": [
            {
                "rank": 1,
                "action": "Check the recipe latency metric.",
                "expected_signal": "Confirm whether latency remains elevated.",
                "read_only_commands": ["kubectl logs deploy/mp-recipe -n app"],
            }
        ],
        "recommendations": [
            {
                "priority": "p2",
                "action": "Review the evidence before remediation.",
                "rationale": "The response is an RCA draft.",
                "risk_level": "low",
            }
        ],
        "limitations": ["Only alert and anomaly evidence were available."],
    }


def test_build_bedrock_rca_uses_forced_tool_call_and_validates_output():
    client = FakeBedrockClient(_tool_response(_valid_tool_input()))
    request = RcaAnalysisRequest(evidence=_evidence())

    response = build_bedrock_rca(
        request,
        region_name="ap-northeast-2",
        model_id="apac.amazon.nova-micro-v1:0",
        client=client,
    )

    assert response.provider == "bedrock"
    assert response.incident_id == "incident-recipe-latency"
    assert client.kwargs["modelId"] == "apac.amazon.nova-micro-v1:0"
    assert client.kwargs["toolConfig"]["toolChoice"] == {
        "tool": {"name": "submit_rca_draft"}
    }


def test_build_bedrock_rca_rejects_missing_tool_use():
    client = FakeBedrockClient({"output": {"message": {"content": [{"text": "hello"}]}}})

    with pytest.raises(BedrockRcaError, match="exactly one"):
        build_bedrock_rca(
            RcaAnalysisRequest(evidence=_evidence()),
            region_name="ap-northeast-2",
            model_id="model",
            client=client,
        )


def test_build_bedrock_rca_rejects_risky_recommendation_without_rollback():
    risky_no_rollback = _valid_tool_input()
    risky_no_rollback["recommendations"] = [
        {
            "priority": "p1",
            "action": "Restart the deployment.",
            "rationale": "Clears the stuck connection pool.",
            "risk_level": "medium",
        }
    ]
    client = FakeBedrockClient(_tool_response(risky_no_rollback))

    with pytest.raises(BedrockRcaError, match="contract validation"):
        build_bedrock_rca(
            RcaAnalysisRequest(evidence=_evidence()),
            region_name="ap-northeast-2",
            model_id="model",
            client=client,
        )


def test_build_bedrock_rca_accepts_risky_recommendation_with_rollback():
    risky_with_rollback = _valid_tool_input()
    risky_with_rollback["recommendations"] = [
        {
            "priority": "p1",
            "action": "Restart the deployment.",
            "rationale": "Clears the stuck connection pool.",
            "risk_level": "medium",
            "rollback": "kubectl rollout undo deployment/mp-recipe -n app",
        }
    ]
    client = FakeBedrockClient(_tool_response(risky_with_rollback))

    response = build_bedrock_rca(
        RcaAnalysisRequest(evidence=_evidence()),
        region_name="ap-northeast-2",
        model_id="model",
        client=client,
    )

    assert response.recommendations[0].rollback == "kubectl rollout undo deployment/mp-recipe -n app"


def test_build_bedrock_rca_rejects_empty_investigation_draft():
    empty = _valid_tool_input()
    empty["causes"] = []
    empty["checks"] = []
    empty["recommendations"] = []
    client = FakeBedrockClient(_tool_response(empty))

    with pytest.raises(BedrockRcaError, match="contract validation"):
        build_bedrock_rca(
            RcaAnalysisRequest(evidence=_evidence()),
            region_name="ap-northeast-2",
            model_id="model",
            client=client,
        )


def test_build_bedrock_rca_surfaces_provider_errors():
    client = FakeBedrockClient(error=RuntimeError("access denied"))

    with pytest.raises(BedrockRcaError, match="Bedrock RCA request failed"):
        build_bedrock_rca(
            RcaAnalysisRequest(evidence=_evidence()),
            region_name="ap-northeast-2",
            model_id="model",
            client=client,
        )


def test_build_bedrock_rca_omits_guardrail_config_when_unset():
    client = FakeBedrockClient(_tool_response(_valid_tool_input()))
    build_bedrock_rca(
        RcaAnalysisRequest(evidence=_evidence()),
        region_name="ap-northeast-2",
        model_id="model",
        client=client,
    )
    assert "guardrailConfig" not in client.kwargs


def test_build_bedrock_rca_applies_guardrail_config_when_both_id_and_version_set():
    client = FakeBedrockClient(_tool_response(_valid_tool_input()))
    build_bedrock_rca(
        RcaAnalysisRequest(evidence=_evidence()),
        region_name="ap-northeast-2",
        model_id="model",
        guardrail_id="gid-123",
        guardrail_version="1",
        client=client,
    )
    assert client.kwargs["guardrailConfig"] == {
        "guardrailIdentifier": "gid-123",
        "guardrailVersion": "1",
        "trace": "enabled",
    }


def test_build_bedrock_rca_omits_guardrail_config_when_only_version_set():
    """Both-or-neither — a lone version without an id is treated as unset, not a partial config."""
    client = FakeBedrockClient(_tool_response(_valid_tool_input()))
    build_bedrock_rca(
        RcaAnalysisRequest(evidence=_evidence()),
        region_name="ap-northeast-2",
        model_id="model",
        guardrail_version="1",
        client=client,
    )
    assert "guardrailConfig" not in client.kwargs


def test_build_bedrock_rca_raises_immediately_on_guardrail_intervention():
    response = _tool_response(_valid_tool_input())
    response["stopReason"] = "guardrail_intervened"
    client = FakeBedrockClient(response)

    with pytest.raises(BedrockRcaError, match="Contextual Grounding Check"):
        build_bedrock_rca(
            RcaAnalysisRequest(evidence=_evidence()),
            region_name="ap-northeast-2",
            model_id="model",
            guardrail_id="gid-123",
            guardrail_version="1",
            client=client,
        )


def test_build_bedrock_rca_guardrail_intervened_defaults_false():
    client = FakeBedrockClient(_tool_response(_valid_tool_input()))
    response = build_bedrock_rca(
        RcaAnalysisRequest(evidence=_evidence()),
        region_name="ap-northeast-2",
        model_id="model",
        client=client,
    )
    assert response.guardrail_intervened is False
