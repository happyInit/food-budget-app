from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.context import get_conn
from app.main import app
from tests.fakes import FakeConn


def _client_with_conn(conn: FakeConn) -> TestClient:
    app.dependency_overrides[get_conn] = lambda: conn
    return TestClient(app)


def _payload(values: list[float]) -> dict:
    start = datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc)
    return {
        "service": "recipe",
        "metric": "p95_latency",
        "points": [
            {
                "timestamp": (start + timedelta(minutes=index)).isoformat(),
                "value": value,
            }
            for index, value in enumerate(values)
        ],
        "config": {
            "baseline_window": 30,
            "min_samples": 30,
            "z_threshold": 3.0,
            "mad_threshold": 3.5,
            "change_rate_threshold": 0.25,
            "consecutive_windows": 3,
            "direction": "high",
        },
    }


def test_health():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "operations"}


def test_evaluate_anomaly():
    baseline = [98.0, 100.0, 102.0] * 10

    with TestClient(app) as client:
        response = client.post(
            "/internal/anomalies/evaluate",
            json=_payload(baseline + [130.0, 170.0, 220.0]),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "anomaly"
    assert body["is_anomaly"] is True
    assert body["service"] == "recipe"
    assert body["metric"] == "p95_latency"
    assert body["consecutive_breaches"] == 3


def test_metrics_endpoint_records_evaluation_request():
    baseline = [98.0, 100.0, 102.0] * 10

    with TestClient(app) as client:
        response = client.post(
            "/internal/anomalies/evaluate",
            json=_payload(baseline + [100.0]),
        )
        metrics = client.get("/metrics")

    assert response.status_code == 200
    assert metrics.status_code == 200
    assert "http_requests_total" in metrics.text


def test_ingest_alertmanager_webhook_normalizes_alerts():
    payload = {
        "version": "4",
        "groupKey": "{}/{alertname=\"AppHighP95Latency\"}:{}",
        "status": "firing",
        "receiver": "operations-webhook",
        "groupLabels": {"alertname": "AppHighP95Latency"},
        "commonLabels": {
            "alertname": "AppHighP95Latency",
            "service": "recipe",
            "severity": "warning",
        },
        "commonAnnotations": {},
        "externalURL": "http://alertmanager:9093",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "AppHighP95Latency",
                    "service": "recipe",
                    "severity": "warning",
                    "namespace": "app",
                    "pod": "mp-recipe-abc123",
                    "container": "recipe",
                },
                "annotations": {"summary": "recipe p95 latency high"},
                "startsAt": "2026-07-29T08:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": "http://prometheus/graph?g0.expr=p95",
                "fingerprint": "recipe-p95-001",
            }
        ],
    }

    conn = FakeConn(
        responses=[
            [
                {
                    "alert_id": "recipe-p95-001",
                    "source": "alertmanager",
                    "status": "firing",
                    "alert_name": "AppHighP95Latency",
                    "service": "recipe",
                    "severity": "warning",
                    "starts_at": datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc),
                    "ends_at": datetime(1, 1, 1, tzinfo=timezone.utc),
                    "received_at": datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc),
                    "pod": "mp-recipe-abc123",
                    "container": "recipe",
                    "labels": payload["alerts"][0]["labels"],
                    "annotations": payload["alerts"][0]["annotations"],
                    "generator_url": payload["alerts"][0]["generatorURL"],
                }
            ]
        ]
    )
    with _client_with_conn(conn) as client:
        response = client.post("/internal/alerts/alertmanager", json=payload)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["received_alert_count"] == 1
    assert body["group_key"] == payload["groupKey"]
    assert body["alerts"][0]["alert_id"] == "recipe-p95-001"
    assert body["alerts"][0]["service"] == "recipe"
    assert body["alerts"][0]["pod"] == "mp-recipe-abc123"
    assert body["incident_count"] == 1
    assert len(conn.executed) == 3
    assert "insert into operations.alerts" in conn.executed[0][0]
    assert "from operations.alerts" in conn.executed[1][0]
    assert "insert into operations.incidents" in conn.executed[2][0]


def test_ingest_alertmanager_webhook_uses_container_when_service_is_missing():
    payload = {
        "version": "4",
        "groupKey": "restart-group",
        "status": "firing",
        "receiver": "operations-webhook",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "AppPodRestartLoop",
                    "container": "recipe",
                    "pod": "mp-recipe-abc123",
                    "severity": "critical",
                },
                "annotations": {},
                "startsAt": "2026-07-29T08:00:00Z",
            }
        ],
    }

    conn = FakeConn(
        responses=[
            [
                {
                    "alert_id": "container-fallback",
                    "source": "alertmanager",
                    "status": "firing",
                    "alert_name": "AppPodRestartLoop",
                    "service": "recipe",
                    "severity": "critical",
                    "starts_at": datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc),
                    "ends_at": None,
                    "received_at": datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc),
                    "pod": "mp-recipe-abc123",
                    "container": "recipe",
                    "labels": payload["alerts"][0]["labels"],
                    "annotations": {},
                    "generator_url": None,
                }
            ]
        ]
    )
    with _client_with_conn(conn) as client:
        response = client.post("/internal/alerts/alertmanager", json=payload)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["alerts"][0]["service"] == "recipe"
    assert len(body["alerts"][0]["alert_id"]) == 64


def test_correlate_incidents():
    start = "2026-07-29T08:00:00Z"
    later = "2026-07-29T08:03:00Z"
    payload = {
        "alerts": [
            {
                "alert_id": "postgres-latency",
                "status": "firing",
                "alert_name": "DatabaseLatency",
                "service": "postgres",
                "severity": "warning",
                "starts_at": start,
                "received_at": start,
                "labels": {},
                "annotations": {},
            },
            {
                "alert_id": "recipe-p95",
                "status": "firing",
                "alert_name": "AppHighP95Latency",
                "service": "recipe",
                "severity": "warning",
                "starts_at": later,
                "received_at": later,
                "labels": {},
                "annotations": {},
            },
        ],
        "config": {
            "dependencies": [
                {"upstream": "postgres", "downstream": "recipe"}
            ]
        },
    }

    with TestClient(app) as client:
        response = client.post("/internal/incidents/correlate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["incident_count"] == 1
    assert body["incidents"][0]["alert_count"] == 2
    assert body["incidents"][0]["suspected_origin_service"] == "postgres"
