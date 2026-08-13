from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.models import EvidencePackage, IncidentCandidate, NormalizedAlert
from app.queries import (
    create_incident_evidence_snapshot,
    get_latest_incident_evidence_snapshot,
    list_anomalies,
    list_anomalies_for_incident_window,
    list_incidents,
)
from tests.fakes import FakeConn


def _package() -> EvidencePackage:
    captured_at = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
    alert = NormalizedAlert(
        alert_id="recipe-p95",
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
        incident_id="incident-recipe-p95",
        title="recipe incident candidate",
        first_seen_at=captured_at,
        last_seen_at=captured_at,
        earliest_alert_id=alert.alert_id,
        earliest_alert_name=alert.alert_name,
        suspected_origin_service="recipe",
        affected_services=["recipe"],
        alert_count=1,
        grouping_reasons=["same_service"],
        alerts=[alert],
    )
    return EvidencePackage(
        incident=incident,
        generated_at=captured_at,
        selection_window_start=captured_at,
        selection_window_end=captured_at,
        anomalies=[],
        alerts=[alert],
    )


def test_creates_compact_incident_evidence_snapshot():
    conn = FakeConn()
    snapshot = asyncio.run(create_incident_evidence_snapshot(conn, _package()))

    assert snapshot.incident_id == "incident-recipe-p95"
    assert len(snapshot.snapshot_id) == 36
    sql, params = conn.executed[0]
    assert "insert into operations.incident_evidence_snapshots" in sql
    assert params[1] == "incident-recipe-p95"
    assert params[3].obj["incident"]["incident_id"] == "incident-recipe-p95"


def test_reads_latest_incident_evidence_snapshot():
    package = _package()
    conn = FakeConn(
        responses=[
            [
                {
                    "snapshot_id": "snapshot-1",
                    "incident_id": package.incident.incident_id,
                    "captured_at": package.generated_at,
                    "package": package.model_dump(mode="json"),
                }
            ]
        ]
    )

    snapshot = asyncio.run(
        get_latest_incident_evidence_snapshot(conn, package.incident.incident_id)
    )

    assert snapshot is not None
    assert snapshot.snapshot_id == "snapshot-1"
    assert snapshot.package.incident.incident_id == package.incident.incident_id
    assert "order by captured_at desc" in conn.executed[0][0]


def test_lists_anomalies_in_dashboard_time_range():
    package = _package()
    anomaly = {
        "metric_id": "service_p95_latency",
        "subject_type": "service",
        "subject_key": "recipe",
        "labels": {"service": "recipe"},
        "evaluated_at": package.generated_at,
        "status": "anomaly",
        "current_value": 1.4,
        "consecutive_breaches": 3,
        "required_consecutive_windows": 3,
    }
    conn = FakeConn(responses=[[anomaly]])

    result = asyncio.run(
        list_anomalies(
            conn,
            start_at=package.generated_at,
            end_at=package.generated_at,
            limit=100,
        )
    )

    assert [item.metric_id for item in result] == ["service_p95_latency"]
    assert "where evaluated_at between" in conn.executed[0][0]


def test_lists_only_confirmed_anomalies_for_incident_evidence_window():
    """Evidence Builder must not pull unconfirmed 'candidate' noise into the
    JSON handed to Bedrock — only status='anomaly' rows are confirmed
    detections."""
    package = _package()
    anomaly = {
        "metric_id": "pod_memory_working_set",
        "subject_type": "pod_container",
        "subject_key": "app/mp-recipe-x/recipe",
        "labels": {"service": "recipe"},
        "evaluated_at": package.generated_at,
        "status": "anomaly",
        "current_value": 1.4,
        "consecutive_breaches": 3,
        "required_consecutive_windows": 3,
    }
    conn = FakeConn(responses=[[anomaly]])

    result = asyncio.run(
        list_anomalies_for_incident_window(
            conn,
            start_at=package.generated_at,
            end_at=package.generated_at,
        )
    )

    assert [item.metric_id for item in result] == ["pod_memory_working_set"]
    sql = conn.executed[0][0]
    assert "where evaluated_at between" in sql
    assert "status = 'anomaly'" in sql


def test_lists_incidents_overlapping_dashboard_time_range():
    package = _package()
    conn = FakeConn(responses=[[package.incident.model_dump(mode="json")]])

    result = asyncio.run(
        list_incidents(
            conn,
            start_at=package.generated_at,
            end_at=package.generated_at,
            limit=100,
        )
    )

    assert [item.incident_id for item in result] == ["incident-recipe-p95"]
    assert "where first_seen_at <= %s and last_seen_at >= %s" in conn.executed[0][0]
