from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.incident_correlator import IncidentCorrelator
from app.models import (
    CorrelationConfig,
    IncidentCorrelationRequest,
    NormalizedAlert,
    ServiceDependency,
)


def _alert(
    alert_id: str,
    *,
    service: str,
    minute: int,
    pod: str | None = None,
) -> NormalizedAlert:
    starts_at = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc) + timedelta(
        minutes=minute
    )
    return NormalizedAlert(
        alert_id=alert_id,
        status="firing",
        alert_name=f"{service}-alert",
        service=service,
        severity="warning",
        starts_at=starts_at,
        ends_at=None,
        received_at=starts_at,
        pod=pod,
        container=service,
        labels={},
        annotations={},
        generator_url=None,
    )


def test_correlates_same_service_alerts_within_time_window():
    result = IncidentCorrelator().correlate(
        IncidentCorrelationRequest(
            alerts=[
                _alert("db-latency", service="recipe", minute=0),
                _alert("recipe-p95", service="recipe", minute=5),
            ]
        )
    )

    assert result.incident_count == 1
    incident = result.incidents[0]
    assert incident.alert_count == 2
    assert incident.suspected_origin_service == "recipe"
    assert incident.earliest_alert_id == "db-latency"
    assert incident.grouping_reasons == ["same_service", "time_window"]


def test_correlates_dependent_services_and_keeps_unrelated_alert_separate():
    result = IncidentCorrelator().correlate(
        IncidentCorrelationRequest(
            alerts=[
                _alert("postgres-latency", service="postgres", minute=0),
                _alert("recipe-p95", service="recipe", minute=3),
                _alert("gateway-5xx", service="gateway", minute=6),
                _alert("chat-p95", service="chat", minute=6),
            ],
            config=CorrelationConfig(
                dependencies=[
                    ServiceDependency(upstream="postgres", downstream="recipe"),
                    ServiceDependency(upstream="recipe", downstream="gateway"),
                ]
            ),
        )
    )

    assert result.incident_count == 2
    related = next(
        incident
        for incident in result.incidents
        if incident.suspected_origin_service == "postgres"
    )
    assert related.affected_services == ["gateway", "postgres", "recipe"]
    assert related.alert_count == 3
    assert "service_dependency" in related.grouping_reasons


def test_does_not_correlate_alerts_outside_time_window():
    result = IncidentCorrelator().correlate(
        IncidentCorrelationRequest(
            alerts=[
                _alert("recipe-p95-first", service="recipe", minute=0),
                _alert("recipe-p95-later", service="recipe", minute=16),
            ]
        )
    )

    assert result.incident_count == 2


def test_incident_id_stays_stable_when_later_alert_joins_group():
    correlator = IncidentCorrelator()
    initial = correlator.correlate(
        IncidentCorrelationRequest(
            alerts=[_alert("postgres-latency", service="postgres", minute=0)]
        )
    )
    updated = correlator.correlate(
        IncidentCorrelationRequest(
            alerts=[
                _alert("postgres-latency", service="postgres", minute=0),
                _alert("postgres-connections", service="postgres", minute=3),
            ]
        )
    )

    assert initial.incidents[0].incident_id == updated.incidents[0].incident_id
    assert updated.incidents[0].alert_count == 2


def test_incident_id_stays_stable_when_tied_alert_joins_with_smaller_alert_id():
    """Regression: two Alertmanager alerts sharing one starts_at is routine
    (several rules firing off the same evaluation cycle), and they can arrive
    in separate webhook calls since group_by=[alertname, service] buckets by
    alertname. Tie-breaking on alert_id alone meant a later-arriving alert
    whose alert_id happens to sort earlier would retroactively become "the
    earliest alert" once it joined the group, changing the computed
    incident_id and producing a duplicate row via ON CONFLICT (incident_id)
    instead of updating the existing incident — confirmed live: two real
    Alertmanager alerts (AlertmanagerFailedToSendAlerts /
    AlertmanagerClusterFailedToSendAlerts, same starts_at) showed up as two
    separate incident cards in the dashboard for the same event."""
    tied_starts_at = datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc)
    first_received = NormalizedAlert(
        alert_id="zzz-arrived-first",  # sorts *after* the second alert_id
        status="firing",
        alert_name="AlertmanagerFailedToSendAlerts",
        service="kube-prometheus-stack-alertmanager",
        severity="warning",
        starts_at=tied_starts_at,
        ends_at=None,
        received_at=tied_starts_at,
        pod=None,
        container=None,
        labels={},
        annotations={},
        generator_url=None,
    )
    second_received = NormalizedAlert(
        alert_id="aaa-arrived-second",  # sorts *before* the first alert_id
        status="firing",
        alert_name="AlertmanagerClusterFailedToSendAlerts",
        service="kube-prometheus-stack-alertmanager",
        severity="critical",
        starts_at=tied_starts_at,
        ends_at=None,
        received_at=tied_starts_at + timedelta(minutes=1),
        pod=None,
        container=None,
        labels={},
        annotations={},
        generator_url=None,
    )

    correlator = IncidentCorrelator()
    initial = correlator.correlate(
        IncidentCorrelationRequest(alerts=[first_received])
    )
    updated = correlator.correlate(
        IncidentCorrelationRequest(alerts=[first_received, second_received])
    )

    assert initial.incidents[0].incident_id == updated.incidents[0].incident_id
    assert updated.incidents[0].alert_count == 2
