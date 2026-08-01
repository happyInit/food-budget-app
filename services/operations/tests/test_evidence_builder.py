from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.evidence_builder import EvidenceBuilder
from app.models import (
    IncidentCandidate,
    KubernetesEventEvidence,
    NormalizedAlert,
    StoredAnomalyCandidate,
)


def _incident() -> IncidentCandidate:
    started_at = datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)
    alert = NormalizedAlert(
        alert_id="recipe-latency",
        status="firing",
        alert_name="AppHighP95Latency",
        service="recipe",
        severity="warning",
        starts_at=started_at,
        received_at=started_at,
        labels={"service": "recipe"},
        annotations={},
    )
    return IncidentCandidate(
        incident_id="incident-recipe-latency",
        title="recipe incident candidate",
        first_seen_at=started_at,
        last_seen_at=started_at + timedelta(minutes=5),
        earliest_alert_id=alert.alert_id,
        earliest_alert_name=alert.alert_name,
        suspected_origin_service="recipe",
        affected_services=["recipe", "gateway"],
        alert_count=1,
        grouping_reasons=["same_service"],
        alerts=[alert],
    )


def _anomaly(
    *, service: str, at: datetime, metric_id: str = "service_p95_latency"
) -> StoredAnomalyCandidate:
    return StoredAnomalyCandidate(
        metric_id=metric_id,
        subject_type="service",
        subject_key=service,
        labels={"service": service},
        evaluated_at=at,
        status="anomaly",
        current_value=842.0,
        z_score=4.7,
        mad_score=5.2,
        change_rate=0.38,
        breached_checks=["z_score", "mad", "change_rate"],
        consecutive_breaches=3,
        required_consecutive_windows=3,
    )


def test_evidence_builder_selects_only_incident_related_anomalies():
    incident = _incident()
    builder = EvidenceBuilder(time_window_minutes=15)
    package = builder.build(
        incident,
        [
            _anomaly(service="recipe", at=incident.first_seen_at + timedelta(minutes=2)),
            _anomaly(service="price", at=incident.first_seen_at + timedelta(minutes=2)),
            _anomaly(service="gateway", at=incident.last_seen_at + timedelta(minutes=15)),
            _anomaly(service="recipe", at=incident.first_seen_at - timedelta(minutes=16)),
        ],
        generated_at=incident.last_seen_at,
    )

    assert [item.subject_key for item in package.anomalies] == ["recipe", "gateway"]
    assert package.anomalies[0].selection_reasons == [
        "incident_time_window",
        "same_service",
    ]
    assert package.alerts[0].alert_id == "recipe-latency"
    assert {item.source for item in package.unavailable_sources} == {
        "logs",
        "traces",
        "kubernetes_events",
        "deployments",
    }


def test_evidence_builder_matches_pod_container_to_affected_service():
    incident = _incident()
    pod_anomaly = StoredAnomalyCandidate(
        metric_id="pod_memory_working_set",
        subject_type="pod_container",
        subject_key="app/mp-recipe-abc/recipe",
        labels={"namespace": "app", "pod": "mp-recipe-abc", "container": "recipe"},
        evaluated_at=incident.first_seen_at,
        status="candidate",
        current_value=250000000.0,
        breached_checks=["z_score"],
        consecutive_breaches=1,
        required_consecutive_windows=3,
    )

    package = EvidenceBuilder().build(incident, [pod_anomaly])

    assert package.anomalies[0].selection_reasons == [
        "incident_time_window",
        "same_container",
    ]


def test_evidence_builder_marks_kubernetes_sources_connected_when_collected():
    incident = _incident()
    event = KubernetesEventEvidence(
        namespace="app",
        event_id="recipe-backoff",
        reason="BackOff",
        message="Back-off restarting failed container",
        occurred_at=incident.first_seen_at,
        count=2,
        pod="mp-recipe-abc",
        selection_reasons=["incident_time_window"],
    )

    package = EvidenceBuilder().build(incident, [], kubernetes_events=[event], deployments=[])

    assert package.kubernetes_events == [event]
    assert {item.source for item in package.unavailable_sources} == {"logs", "traces"}
