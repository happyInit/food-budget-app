from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.loki_evidence import LokiEvidenceCollector, normalize_log_pattern
from app.models import IncidentCandidate, NormalizedAlert


class FakeLokiApiClient:
    def __init__(self, streams):
        self._streams = streams

    async def query_range(self, query, *, start_at, end_at, limit):
        return self._streams


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


def test_normalize_log_pattern_masks_numbers_and_uuids():
    line = "Failed to connect to postgres after 3 retries, request_id=a1b2c3d4-1111-2222-3333-444455556666"
    assert normalize_log_pattern(line) == (
        "Failed to connect to postgres after # retries, request_id=<uuid>"
    )


def test_collects_incident_scoped_error_log_patterns():
    streams = [
        {
            "stream": {"namespace": "app", "container": "recipe"},
            "values": [
                ["1785398520000000000", "Failed to connect to postgres after 3 retries"],
                ["1785398521000000000", "Failed to connect to postgres after 7 retries"],
                ["1785398522000000000", "Failed to connect to postgres after 2 retries"],
            ],
        },
        {
            "stream": {"namespace": "app", "container": "gateway"},
            "values": [
                ["1785398523000000000", "upstream timeout calling recipe"],
            ],
        },
    ]
    collector = LokiEvidenceCollector(
        Settings(operations_loki_max_samples_per_pattern=2),
        client=FakeLokiApiClient(streams),
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
    recipe_pattern = next(item for item in result if item.container == "recipe")
    assert recipe_pattern.pattern == "Failed to connect to postgres after # retries"
    assert recipe_pattern.count == 3
    assert len(recipe_pattern.samples) == 2
    assert recipe_pattern.first_seen_at < recipe_pattern.last_seen_at

    gateway_pattern = next(item for item in result if item.container == "gateway")
    assert gateway_pattern.count == 1
