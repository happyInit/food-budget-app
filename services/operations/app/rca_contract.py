"""Provider-neutral RCA request/response contract.

This module deliberately has no AWS SDK or HTTP client.  It defines the stable
boundary between deterministic Evidence collection and a future Bedrock RCA
provider, and supplies a deterministic mock for API/UI integration tests.
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


class RcaRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: RcaPriority
    action: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class RcaAnalysisResponse(BaseModel):
    """Provider output saved and shown only as an RCA *draft*."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["v1"] = "v1"
    provider: Literal["mock", "bedrock"]
    status: Literal["draft"] = "draft"
    incident_id: str
    generated_at: str
    causes: list[RcaCause]
    propagation_path: list[RcaPropagationHop]
    checks: list[RcaCheck]
    recommendations: list[RcaRecommendation]
    limitations: list[str]


def build_mock_rca(request: RcaAnalysisRequest) -> RcaAnalysisResponse:
    """Return a deterministic, explicitly non-diagnostic RCA draft.

    The mock only repeats facts already present in Evidence.  It must never be
    presented as a root-cause conclusion and is safe to use before AWS access
    and prompt/provider work are available.
    """

    evidence = request.evidence
    incident = evidence.incident
    alert = incident.alerts[0]
    references = [
        RcaEvidenceReference(
            source="alert",
            reference_id=alert.alert_id,
            summary=f"{alert.alert_name} alert for {alert.service}",
        )
    ]
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
                evidence=references,
            )
        ],
        propagation_path=path,
        checks=[
            RcaCheck(
                rank=1,
                action="Review the linked alert and anomaly evidence.",
                expected_signal="Confirm whether the incident time window contains a common trigger.",
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
