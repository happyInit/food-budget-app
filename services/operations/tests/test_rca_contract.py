from __future__ import annotations

from datetime import datetime, timezone

from app.models import EvidenceAnomaly, EvidencePackage, IncidentCandidate, NormalizedAlert
from app.rca_contract import RcaAnalysisRequest, build_mock_rca


def _evidence() -> EvidencePackage:
    captured_at = datetime(2026, 8, 1, 3, 0, tzinfo=timezone.utc)
    alert = NormalizedAlert(
        alert_id="recipe-latency",
        status="firing",
        alert_name="AppHighP95Latency",
        service="recipe",
        severity="warning",
        starts_at=captured_at,
        received_at=captured_at,
        labels={"service": "recipe"},
        annotations={},
    )
    incident = IncidentCandidate(
        incident_id="incident-recipe-latency",
        title="recipe incident candidate",
        first_seen_at=captured_at,
        last_seen_at=captured_at,
        earliest_alert_id=alert.alert_id,
        earliest_alert_name=alert.alert_name,
        suspected_origin_service="recipe",
        affected_services=["recipe", "gateway"],
        alert_count=1,
        grouping_reasons=["same_service"],
        alerts=[alert],
    )
    anomaly = EvidenceAnomaly(
        metric_id="service_p95_latency",
        subject_type="service",
        subject_key="recipe",
        labels={"service": "recipe"},
        evaluated_at=captured_at,
        status="anomaly",
        current_value=842.0,
        breached_checks=["z_score"],
        consecutive_breaches=3,
        required_consecutive_windows=3,
        selection_reasons=["same_service"],
    )
    return EvidencePackage(
        incident=incident,
        generated_at=captured_at,
        selection_window_start=captured_at,
        selection_window_end=captured_at,
        anomalies=[anomaly],
        alerts=[alert],
    )


def test_mock_rca_returns_a_deterministic_draft_with_evidence_references():
    request = RcaAnalysisRequest(evidence=_evidence())

    response = build_mock_rca(request)

    assert response.provider == "mock"
    assert response.status == "draft"
    assert response.incident_id == "incident-recipe-latency"
    assert [reference.source for reference in response.causes[0].evidence] == [
        "alert",
        "anomaly",
    ]
    assert [hop.service for hop in response.propagation_path] == ["recipe", "gateway"]
    assert "no Bedrock" in response.limitations[0]


def test_mock_rca_is_stable_for_the_same_evidence():
    request = RcaAnalysisRequest(evidence=_evidence())

    assert build_mock_rca(request).model_dump() == build_mock_rca(request).model_dump()
