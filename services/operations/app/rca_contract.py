"""Provider-neutral RCA request/response contract.

This module defines the stable boundary between deterministic Evidence
collection and Bedrock RCA, and supplies a deterministic mock for API/UI tests.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import EvidencePackage


RcaEvidenceSource = Literal[
    "alert",
    "anomaly",
    "log",
    "trace",
    "kubernetes_event",
    "deployment",
]
RcaConfidence = Literal["low", "medium", "high"]
RcaPriority = Literal["p0", "p1", "p2", "p3"]


class BedrockRcaError(RuntimeError):
    """A Bedrock call failed or returned an unusable RCA tool response.

    The API layer turns this into an explicit upstream error; it must never
    silently substitute a mock result.
    """


class RcaAnalysisRequest(BaseModel):
    """Input passed to an RCA provider after Evidence has been assembled."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"
    evidence: EvidencePackage


class RcaEvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: RcaEvidenceSource
    reference_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class RcaCause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    summary: str = Field(min_length=1)
    confidence: RcaConfidence
    analysis: str = Field(min_length=1)
    evidence: list[RcaEvidenceReference] = Field(min_length=1)


class RcaPropagationHop(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1)
    observation: str = Field(min_length=1)


class RcaCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    action: str = Field(min_length=1)
    expected_signal: str = Field(min_length=1)
    read_only_commands: list[str] = Field(min_length=1, max_length=3)


class RcaRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: RcaPriority
    action: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    precondition: str | None = None


class RcaAnalysisResponse(BaseModel):
    """Provider output saved and shown only as an RCA *draft*."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"
    provider: Literal["mock", "bedrock"]
    status: Literal["draft"] = "draft"
    incident_id: str
    generated_at: str
    causes: list[RcaCause] = Field(min_length=1)
    propagation_path: list[RcaPropagationHop]
    checks: list[RcaCheck] = Field(min_length=1)
    recommendations: list[RcaRecommendation] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    cached: bool = False


def build_mock_rca(request: RcaAnalysisRequest) -> RcaAnalysisResponse:
    """Return a deterministic, explicitly non-diagnostic RCA draft.

    The mock only repeats facts already present in Evidence.  It must never be
    presented as a root-cause conclusion and is safe to use before AWS access
    and prompt/provider work are available.
    """

    evidence = request.evidence
    incident = evidence.incident
    anomaly_labels = evidence.anomalies[0].labels if evidence.anomalies else {}
    namespace = anomaly_labels.get("namespace", "<namespace>")
    pod = anomaly_labels.get("pod", "<pod>")
    references: list[RcaEvidenceReference] = []
    if incident.alerts:
        alert = incident.alerts[0]
        references.append(
            RcaEvidenceReference(
                source="alert",
                reference_id=alert.alert_id,
                summary=f"{alert.alert_name} alert for {alert.service}",
            )
        )
    if evidence.anomalies:
        anomaly = evidence.anomalies[0]
        references.append(
            RcaEvidenceReference(
                source="anomaly",
                reference_id=anomaly.metric_id,
                summary=f"{anomaly.metric_id} anomaly on {anomaly.subject_key}",
            )
        )

    services = [incident.suspected_origin_service, *incident.affected_services]
    unique_services = list(dict.fromkeys(services))
    path = [
        RcaPropagationHop(service=service, observation="Incident correlation scope")
        for service in unique_services
    ]
    return RcaAnalysisResponse(
        provider="mock",
        incident_id=incident.incident_id,
        generated_at=evidence.generated_at.isoformat(),
        causes=[
            RcaCause(
                rank=1,
                summary="Mock draft: root cause has not been inferred.",
                confidence="low",
                analysis="저장된 Evidence만으로는 근본 원인을 확정할 수 없습니다.",
                evidence=references,
            )
        ],
        propagation_path=path,
        checks=[
            RcaCheck(
                rank=1,
                action="Review the linked anomaly and any available alert evidence.",
                expected_signal="Confirm whether the incident time window contains a common trigger.",
                read_only_commands=[f"kubectl describe pod {pod} -n {namespace}"],
            )
        ],
        recommendations=[
            RcaRecommendation(
                priority="p2",
                action="Do not automate remediation from this mock response.",
                rationale="The mock is a contract test fixture, not an RCA model result.",
            )
        ],
        limitations=[
            "Mock response only; no Bedrock or other AI provider was called.",
            "Root-cause inference requires a future provider implementation and review.",
        ],
    )


def build_bedrock_rca(
    request: RcaAnalysisRequest,
    *,
    region_name: str,
    model_id: str,
    client=None,
) -> RcaAnalysisResponse:
    """Call Bedrock Converse and validate its forced tool-use RCA draft.

    ``client`` is injectable so unit tests do not require AWS credentials or
    network access. Credentials are resolved by boto3's standard provider
    chain (local profile, then EC2 Instance Profile in production).
    """
    from app.rca_prompt import (
        RCA_TOOL_NAME,
        RCA_TOOL_SCHEMA,
        SYSTEM_PROMPT,
        format_evidence_for_prompt,
    )

    if client is None:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - packaging safeguard
            raise BedrockRcaError("boto3 is not installed") from exc
        client = boto3.client("bedrock-runtime", region_name=region_name)

    evidence = request.evidence
    expected_fields = {
        "causes",
        "propagation_path",
        "checks",
        "recommendations",
        "limitations",
    }

    def invoke(repair_instruction: str | None = None) -> dict:
        system = [{"text": SYSTEM_PROMPT}]
        if repair_instruction:
            system.append({"text": repair_instruction})
        try:
            response = client.converse(
                modelId=model_id,
                system=system,
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": format_evidence_for_prompt(evidence)}],
                    }
                ],
                toolConfig={
                    "tools": [RCA_TOOL_SCHEMA],
                    "toolChoice": {"tool": {"name": RCA_TOOL_NAME}},
                },
            )
        except Exception as exc:
            raise BedrockRcaError(f"Bedrock RCA request failed: {exc}") from exc
        content = response.get("output", {}).get("message", {}).get("content", [])
        if not isinstance(content, list):
            raise BedrockRcaError("Bedrock RCA response content was malformed")
        tool_inputs = [
            tool_use["input"]
            for block in content
            if isinstance(block, dict)
            and isinstance((tool_use := block.get("toolUse")), dict)
            and tool_use.get("name") == RCA_TOOL_NAME
            and "input" in tool_use
        ]
        if len(tool_inputs) != 1 or not isinstance(tool_inputs[0], dict):
            raise BedrockRcaError(
                "Bedrock RCA response did not contain exactly one valid submit_rca_draft tool call"
            )
        return tool_inputs[0]

    validation_error: Exception | None = None
    for attempt in range(2):
        tool_input = invoke(
            "Your previous draft was rejected. Every cause must include at least one "
            "real Evidence reference; causes, checks, recommendations, and limitations "
            "must all be non-empty. Each cause must include analysis and each check must include one or more read_only_commands. "
            "Submit a corrected draft only."
            if attempt
            else None
        )
        unexpected_fields = set(tool_input) - expected_fields
        if unexpected_fields:
            raise BedrockRcaError(
                "Bedrock RCA tool input contained unexpected fields: "
                + ", ".join(sorted(unexpected_fields))
            )
        payload = {
            **tool_input,
            "contract_version": "v1",
            "provider": "bedrock",
            "status": "draft",
            "incident_id": evidence.incident.incident_id,
            "generated_at": evidence.generated_at.isoformat(),
        }
        try:
            return RcaAnalysisResponse.model_validate(payload)
        except Exception as exc:
            validation_error = exc
    raise BedrockRcaError(
        f"Bedrock RCA response failed contract validation after one repair retry: {validation_error}"
    ) from validation_error
