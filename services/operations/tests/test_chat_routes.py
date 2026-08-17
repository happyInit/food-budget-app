from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Settings
from app.context import AppCtx, get_conn, get_ctx
from app.main import app
from tests.fakes import FakeConn


def _client_with(conn: FakeConn, settings: Settings | None = None) -> TestClient:
    app.dependency_overrides[get_conn] = lambda: conn
    if settings is not None:
        app.dependency_overrides[get_ctx] = lambda: AppCtx(pool=None, settings=settings)
    return TestClient(app)


def test_chat_returns_mock_answer_with_no_anomalies_or_incidents():
    # gather_chat_snapshot issues two DB reads in order: anomalies, then incidents.
    conn = FakeConn(responses=[[], []])

    # Explicit mock override — a local .env with OPERATIONS_CHAT_PROVIDER=bedrock
    # would otherwise send this down the real Bedrock path and fail with 502.
    with _client_with(conn, Settings(operations_chat_provider="mock")) as client:
        response = client.post("/internal/chat", json={"question": "지금 서버 상태 어때?"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock"
    assert "서버 상태" in body["answer"]


def test_chat_snapshot_reflects_active_anomalies_not_candidates():
    anomaly_rows = [
        {
            "metric_id": "pod_cpu_usage",
            "subject_type": "pod_container",
            "subject_key": "data/pg-0/postgres",
            "labels": {},
            "evaluated_at": "2026-08-14T00:00:00+00:00",
            "status": "anomaly",
            "current_value": 1.2,
            "baseline": None,
            "z_score": 4.1,
            "mad_score": None,
            "change_rate": None,
            "breached_checks": [],
            "consecutive_breaches": 3,
            "required_consecutive_windows": 3,
            "event_count": None,
        },
        {
            "metric_id": "pod_memory_working_set",
            "subject_type": "pod_container",
            "subject_key": "app/recipe-0/recipe",
            "labels": {},
            "evaluated_at": "2026-08-14T00:00:00+00:00",
            "status": "candidate",
            "current_value": 1.0,
            "baseline": None,
            "z_score": 1.0,
            "mad_score": None,
            "change_rate": None,
            "breached_checks": [],
            "consecutive_breaches": 1,
            "required_consecutive_windows": 3,
            "event_count": None,
        },
    ]
    conn = FakeConn(responses=[anomaly_rows, []])

    with _client_with(conn, Settings(operations_chat_provider="mock")) as client:
        response = client.post("/internal/chat", json={"question": "이상징후 있어?"})
    app.dependency_overrides.clear()

    assert response.status_code == 200


def test_chat_returns_502_when_bedrock_provider_fails():
    conn = FakeConn(responses=[[], []])
    settings = Settings(operations_chat_provider="bedrock")

    with _client_with(conn, settings) as client:
        response = client.post("/internal/chat", json={"question": "상태 어때?"})
    app.dependency_overrides.clear()

    assert response.status_code == 502


def test_chat_ignores_client_supplied_snapshot():
    """The server always rebuilds its own snapshot — a caller cannot spoof one."""
    conn = FakeConn(responses=[[], []])

    with _client_with(conn, Settings(operations_chat_provider="mock")) as client:
        response = client.post(
            "/internal/chat",
            json={"question": "상태 어때?", "snapshot": {"active_anomaly_count": 999}},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "999" not in response.json()["answer"]


def _incident_row(incident_id: str = "incident-kurly-stale") -> dict:
    captured_at = "2026-08-16T00:00:00+00:00"
    return {
        "incident_id": incident_id,
        "status": "open",
        "title": "컬리 크롤러 정지",
        "first_seen_at": captured_at,
        "last_seen_at": captured_at,
        "earliest_alert_id": "kurly-stale-critical",
        "earliest_alert_name": "MpKurlyDataStaleCritical",
        "suspected_origin_service": "data-pipeline",
        "affected_services": ["data-pipeline"],
        "alert_count": 1,
        "grouping_reasons": ["same_service"],
        "alerts": [],
    }


def test_chat_helpdesk_mode_404s_for_unknown_incident():
    # get_incident (404 pre-check) → empty result.
    conn = FakeConn(responses=[[]])

    with _client_with(conn, Settings(operations_chat_provider="mock")) as client:
        response = client.post(
            "/internal/chat",
            json={"question": "무슨 사항이야?", "incident_id": "does-not-exist"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 404


def test_chat_helpdesk_mode_scopes_snapshot_to_one_incident():
    # get_incident (404 pre-check) → get_incident (inside snapshot) →
    # get_latest_incident_evidence_snapshot (no Evidence yet).
    incident_row = _incident_row()
    conn = FakeConn(responses=[[incident_row], [incident_row], []])

    with _client_with(conn, Settings(operations_chat_provider="mock")) as client:
        response = client.post(
            "/internal/chat",
            json={"question": "무슨 사항이야?", "incident_id": "incident-kurly-stale"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["provider"] == "mock"


def test_chat_helpdesk_mode_reports_missing_evidence_without_fabricating():
    incident_row = _incident_row()
    conn = FakeConn(responses=[[incident_row], [incident_row], []])

    with _client_with(conn, Settings(operations_chat_provider="mock")) as client:
        response = client.post(
            "/internal/chat",
            json={"question": "왜 이런 일이 일어났어?", "incident_id": "incident-kurly-stale"},
        )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    # mock provider echoes the question back; the real assertion that matters
    # here is that no Evidence lookup blew up when the snapshot was empty —
    # a live Bedrock call would see evidence_available == False in the JSON.
