from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.models import IncidentCandidate, NormalizedAlert
from app.tempo_evidence import TempoEvidenceCollector


class FakeTempoApiClient:
    def __init__(self, *, error_traces, slow_traces):
        self._error_traces = error_traces
        self._slow_traces = slow_traces

    async def search(self, query, *, start_at, end_at, limit):
        if "status = error" in query:
            return self._error_traces
        return self._slow_traces


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


def test_collects_error_and_slow_traces_without_duplicates():
    shared_trace = {
        "traceID": "trace-both",
        "rootServiceName": "recipe",
        "durationMs": 1500,
        "startTimeUnixNano": "1785398520000000000",
    }
    error_only = {
        "traceID": "trace-error-only",
        "rootServiceName": "gateway",
        "durationMs": 200,
        "startTimeUnixNano": "1785398521000000000",
    }
    slow_only = {
        "traceID": "trace-slow-only",
        "rootServiceName": "recipe",
        "durationMs": 2500,
        "startTimeUnixNano": "1785398522000000000",
        "spanSets": [{"matched": 3}],
    }
    client = FakeTempoApiClient(
        error_traces=[shared_trace, error_only],
        slow_traces=[shared_trace, slow_only],
    )
    collector = TempoEvidenceCollector(Settings(), client=client)
    incident = _incident()

    result = asyncio.run(
        collector.collect(
            incident,
            start_at=incident.first_seen_at - timedelta(minutes=15),
            end_at=incident.last_seen_at + timedelta(minutes=15),
        )
    )

    assert len(result) == 3
    by_id = {item.trace_id: item for item in result}

    assert by_id["trace-both"].has_error is True
    assert "error_span" in by_id["trace-both"].selection_reasons
    assert "slow_trace_threshold" in by_id["trace-both"].selection_reasons

    assert by_id["trace-error-only"].has_error is True
    assert by_id["trace-error-only"].span_count == 1

    assert by_id["trace-slow-only"].has_error is False
    assert by_id["trace-slow-only"].span_count == 3

    assert result[0].duration_ms >= result[1].duration_ms >= result[2].duration_ms


def test_limits_result_to_configured_max_traces():
    traces = [
        {
            "traceID": f"trace-{i}",
            "rootServiceName": "recipe",
            "durationMs": 1000 + i,
            "startTimeUnixNano": "1785398520000000000",
        }
        for i in range(5)
    ]
    client = FakeTempoApiClient(error_traces=[], slow_traces=traces)
    collector = TempoEvidenceCollector(
        Settings(operations_tempo_max_traces=2), client=client
    )
    incident = _incident()

    result = asyncio.run(
        collector.collect(
            incident,
            start_at=incident.first_seen_at - timedelta(minutes=15),
            end_at=incident.last_seen_at + timedelta(minutes=15),
        )
    )

    assert len(result) == 2
    assert result[0].duration_ms == 1004
