from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.context import AppCtx, get_conn, get_ctx
import httpx

from app.main import app, get_loki_evidence_collector
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


def _evidence_package_json() -> dict:
    captured_at = "2026-08-01T09:00:00Z"
    alert = {
        "alert_id": "recipe-p95",
        "status": "firing",
        "alert_name": "AppHighP95Latency",
        "service": "recipe",
        "severity": "warning",
        "starts_at": captured_at,
        "received_at": captured_at,
        "labels": {"service": "recipe"},
        "annotations": {},
    }
    incident = {
        "incident_id": "incident-recipe-p95",
        "title": "recipe incident candidate",
        "first_seen_at": captured_at,
        "last_seen_at": captured_at,
        "earliest_alert_id": alert["alert_id"],
        "earliest_alert_name": alert["alert_name"],
        "suspected_origin_service": "recipe",
        "affected_services": ["recipe"],
        "alert_count": 1,
        "grouping_reasons": ["same_service"],
        "alerts": [alert],
    }
    return {
        "incident": incident,
        "generated_at": captured_at,
        "selection_window_start": captured_at,
        "selection_window_end": captured_at,
        "anomalies": [],
        "alerts": [alert],
    }


def test_build_incident_rca_returns_mock_draft_from_latest_snapshot():
    package = _evidence_package_json()
    conn = FakeConn(
        responses=[
            [
                {
                    "snapshot_id": "snapshot-1",
                    "incident_id": "incident-recipe-p95",
                    "captured_at": package["generated_at"],
                    "package": package,
                }
            ]
        ]
    )

    # Explicit mock override — this test asserts mock behavior specifically,
    # so it must not depend on the ambient OPERATIONS_RCA_PROVIDER env var
    # (a local .env with OPERATIONS_RCA_PROVIDER=bedrock would otherwise send
    # this down the real Bedrock path and fail with 502, not 200).
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_ctx] = lambda: AppCtx(
        pool=None,
        settings=Settings(operations_rca_provider="mock"),
    )
    with TestClient(app) as client:
        response = client.post("/internal/incidents/incident-recipe-p95/rca")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock"
    assert body["status"] == "draft"
    assert body["incident_id"] == "incident-recipe-p95"
    assert "no Bedrock" in body["limitations"][0]


def test_build_incident_rca_404s_when_incident_does_not_exist():
    # get_latest_incident_evidence_snapshot -> none, then get_incident -> none.
    conn = FakeConn(responses=[[], []])

    with _client_with_conn(conn) as client:
        response = client.post("/internal/incidents/incident-recipe-p95/rca")
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert "incident was not found" in response.json()["detail"]


def test_build_incident_rca_auto_builds_evidence_when_missing():
    """No manual "build evidence first" step required — a missing snapshot
    is built on the fly from the incident's own alerts/anomaly window rather
    than 404ing and telling the caller to call a separate endpoint first."""
    package = _evidence_package_json()
    conn = FakeConn(
        responses=[
            [],  # get_latest_incident_evidence_snapshot: none yet
            [package["incident"]],  # get_incident
            [],  # list_anomalies_for_incident_window
        ]
    )

    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_ctx] = lambda: AppCtx(
        pool=None,
        settings=Settings(operations_rca_provider="mock"),
    )
    with TestClient(app) as client:
        response = client.post("/internal/incidents/incident-recipe-p95/rca")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock"
    assert body["incident_id"] == "incident-recipe-p95"
    # The evidence snapshot insert ran as part of the same request.
    assert any(
        "insert into operations.incident_evidence_snapshots" in sql
        for sql, _ in conn.executed
    )


class _FailingLokiCollector:
    async def collect(self, *args, **kwargs):
        raise httpx.ConnectError("all connection attempts failed")


def test_build_incident_rca_degrades_gracefully_when_loki_is_unreachable():
    """A down evidence source (e.g. Loki OOM-crashlooping) must not turn an
    ordinary RCA request into an unhandled 500 — it should degrade the report
    the same way a disabled/unconfigured source already does, not crash it.
    Reproduces the live 2026-08-17 incident: httpx.ConnectError propagating
    out of loki_collector.collect() past _build_and_persist_incident_evidence.
    """
    package = _evidence_package_json()
    conn = FakeConn(
        responses=[
            [],  # get_latest_incident_evidence_snapshot: none yet
            [package["incident"]],  # get_incident
            [],  # list_anomalies_for_incident_window
        ]
    )

    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_ctx] = lambda: AppCtx(
        pool=None,
        settings=Settings(operations_rca_provider="mock"),
    )
    app.dependency_overrides[get_loki_evidence_collector] = lambda: _FailingLokiCollector()
    with TestClient(app) as client:
        response = client.post("/internal/incidents/incident-recipe-p95/rca")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock"


def test_build_incident_rca_surfaces_502_when_bedrock_call_fails():
    """The route wires a real build_bedrock_rca call — no client injection point
    exists at the HTTP layer, so this test exercises the real (uncredentialed,
    no-network) failure path and checks it surfaces as a clean 502 rather than
    a raw exception. Success-path behavior (forced tool use, response shape,
    guardrail wiring) is covered at the contract level in test_bedrock_rca.py,
    where a fake client can be injected directly.
    """
    package = _evidence_package_json()
    conn = FakeConn(
        responses=[
            [
                {
                    "snapshot_id": "snapshot-1",
                    "incident_id": "incident-recipe-p95",
                    "captured_at": package["generated_at"],
                    "package": package,
                }
            ]
        ]
    )
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_ctx] = lambda: AppCtx(
        pool=None,
        settings=Settings(operations_rca_provider="bedrock"),
    )

    with TestClient(app) as client:
        response = client.post("/internal/incidents/incident-recipe-p95/rca")
    app.dependency_overrides.clear()

    assert response.status_code == 502
    assert "Bedrock RCA request failed" in response.json()["detail"]
