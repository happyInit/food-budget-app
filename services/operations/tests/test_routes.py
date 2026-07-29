from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app


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
