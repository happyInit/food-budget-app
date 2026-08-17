"""Integration coverage for the helpdesk Slack pre-alert wired into
ingest_alertmanager_webhook — first-sighting-only dispatch and the
never-fail-ingestion guarantee, at the route level rather than unit-testing
slack_notifier alone (see test_slack_notifier.py for that)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.context import AppCtx, get_conn, get_ctx
from app.main import app
from tests.fakes import FakeConn


def _client_with(
    conn: FakeConn, settings: Settings, *, raise_server_exceptions: bool = True
) -> TestClient:
    app.dependency_overrides[get_conn] = lambda: conn
    app.dependency_overrides[get_ctx] = lambda: AppCtx(pool=None, settings=settings)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _alertmanager_payload() -> dict:
    return {
        "version": "4",
        "groupKey": "{}/{alertname=\"MpKurlyDataStaleCritical\"}:{}",
        "status": "firing",
        "receiver": "operations-webhook",
        "groupLabels": {"alertname": "MpKurlyDataStaleCritical"},
        "commonLabels": {
            "alertname": "MpKurlyDataStaleCritical",
            "service": "data-pipeline",
            "severity": "critical",
        },
        "commonAnnotations": {},
        "externalURL": "http://alertmanager:9093",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "MpKurlyDataStaleCritical",
                    "service": "data-pipeline",
                    "severity": "critical",
                },
                "annotations": {"summary": "컬리 정상 수집 시각이 48시간 넘게 갱신되지 않음"},
                "startsAt": "2026-08-16T08:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": "http://prometheus/graph?g0.expr=stale",
                "fingerprint": "kurly-stale-001",
            }
        ],
    }


def _alert_row() -> dict:
    return {
        "alert_id": "kurly-stale-001",
        "source": "alertmanager",
        "status": "firing",
        "alert_name": "MpKurlyDataStaleCritical",
        "service": "data-pipeline",
        "severity": "critical",
        "starts_at": datetime(2026, 8, 16, 8, 0, tzinfo=timezone.utc),
        "ends_at": datetime(1, 1, 1, tzinfo=timezone.utc),
        "received_at": datetime(2026, 8, 16, 8, 0, tzinfo=timezone.utc),
        "pod": None,
        "container": None,
        "labels": _alertmanager_payload()["alerts"][0]["labels"],
        "annotations": _alertmanager_payload()["alerts"][0]["annotations"],
        "generator_url": _alertmanager_payload()["alerts"][0]["generatorURL"],
    }


def test_new_incident_triggers_slack_pre_alert(monkeypatch):
    calls = []

    async def fake_send(incident, *, settings):
        calls.append(incident.incident_id)
        return True

    monkeypatch.setattr("app.main.send_incident_pre_alert", fake_send)

    # Responses in call order: alert lookup (nearby), incidents upsert RETURNING.
    conn = FakeConn(
        responses=[
            [_alert_row()],
            [{"inserted": True}],
        ]
    )
    settings = Settings(operations_slack_webhook_url="https://hooks.slack.example/x")

    with _client_with(conn, settings) as client:
        response = client.post("/internal/alerts/alertmanager", json=_alertmanager_payload())
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(calls) == 1


def test_repeat_incident_does_not_resend_slack_pre_alert(monkeypatch):
    calls = []

    async def fake_send(incident, *, settings):
        calls.append(incident.incident_id)
        return True

    monkeypatch.setattr("app.main.send_incident_pre_alert", fake_send)

    # inserted=False → an existing Incident was refreshed, not created.
    conn = FakeConn(
        responses=[
            [_alert_row()],
            [{"inserted": False}],
        ]
    )
    settings = Settings(operations_slack_webhook_url="https://hooks.slack.example/x")

    with _client_with(conn, settings) as client:
        response = client.post("/internal/alerts/alertmanager", json=_alertmanager_payload())
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert calls == []


def test_slack_dispatch_failure_would_break_ingestion_if_it_ever_raised(monkeypatch):
    """Documents why slack_notifier.send_incident_pre_alert must never raise.

    This route deliberately does not wrap the call in its own try/except —
    the "never fails Alert ingestion" guarantee lives entirely in
    slack_notifier (see test_slack_notifier.py's webhook-failure test). If
    that contract broke, ingestion would break too, which is what this test
    demonstrates by monkeypatching a broken (raising) replacement.
    """

    async def failing_send(incident, *, settings):
        raise RuntimeError("should never propagate — slack_notifier swallows this normally")

    monkeypatch.setattr("app.main.send_incident_pre_alert", failing_send)

    conn = FakeConn(
        responses=[
            [_alert_row()],
            [{"inserted": True}],
        ]
    )
    settings = Settings(operations_slack_webhook_url="https://hooks.slack.example/x")

    with _client_with(conn, settings, raise_server_exceptions=False) as client:
        response = client.post("/internal/alerts/alertmanager", json=_alertmanager_payload())
    app.dependency_overrides.clear()

    assert response.status_code == 500
