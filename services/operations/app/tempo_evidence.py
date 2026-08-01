from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings
from app.models import IncidentCandidate, TraceEvidence


class TempoApiClient:
    """Small read-only Tempo search client used only for incident evidence."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    async def search(
        self,
        query: str,
        *,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        params = {
            "q": query,
            "start": int(start_at.timestamp()),
            "end": int(end_at.timestamp()),
            "limit": limit,
        }
        if self._client is not None:
            response = await self._client.get("/api/search", params=params)
        else:
            async with httpx.AsyncClient(
                base_url=self._settings.operations_tempo_url,
                timeout=self._settings.operations_tempo_query_timeout_seconds,
            ) as client:
                response = await client.get("/api/search", params=params)
        response.raise_for_status()
        payload = response.json()
        return payload.get("traces", [])


class TempoEvidenceCollector:
    """Collect incident-scoped slow or error traces for one Incident's services."""

    def __init__(self, settings: Settings, client: TempoApiClient | None = None) -> None:
        self._settings = settings
        self._client = client or TempoApiClient(settings)

    async def collect(
        self,
        incident: IncidentCandidate,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> list[TraceEvidence]:
        services = {incident.suspected_origin_service, *incident.affected_services}
        selector = "|".join(sorted(services))
        limit = self._settings.operations_tempo_max_traces
        threshold_ms = self._settings.operations_tempo_slow_trace_threshold_ms

        error_traces = await self._client.search(
            f'{{ resource.service.name =~ "{selector}" && status = error }}',
            start_at=start_at,
            end_at=end_at,
            limit=limit,
        )
        slow_traces = await self._client.search(
            f'{{ resource.service.name =~ "{selector}" && duration > {threshold_ms}ms }}',
            start_at=start_at,
            end_at=end_at,
            limit=limit,
        )

        traces_by_id: dict[str, dict[str, Any]] = {}
        match_reasons: dict[str, set[str]] = {}
        for trace in error_traces:
            trace_id = trace["traceID"]
            traces_by_id[trace_id] = trace
            match_reasons.setdefault(trace_id, set()).add("error_span")
        for trace in slow_traces:
            trace_id = trace["traceID"]
            traces_by_id.setdefault(trace_id, trace)
            match_reasons.setdefault(trace_id, set()).add("slow_trace_threshold")

        evidence = [
            self._to_evidence(traces_by_id[trace_id], reasons)
            for trace_id, reasons in match_reasons.items()
        ]
        return sorted(evidence, key=lambda item: item.duration_ms, reverse=True)[:limit]

    @staticmethod
    def _to_evidence(trace: dict[str, Any], reasons: set[str]) -> TraceEvidence:
        started_at = datetime.fromtimestamp(
            int(trace.get("startTimeUnixNano", 0)) / 1_000_000_000, tz=timezone.utc
        )
        span_sets = trace.get("spanSets") or (
            [trace["spanSet"]] if trace.get("spanSet") else []
        )
        span_count = sum(int(item.get("matched", 1)) for item in span_sets) or 1
        return TraceEvidence(
            trace_id=trace["traceID"],
            root_service=trace.get("rootServiceName"),
            duration_ms=float(trace.get("durationMs", 0)),
            has_error="error_span" in reasons,
            span_count=span_count,
            started_at=started_at,
            selection_reasons=[
                "incident_time_window",
                "incident_service_trace",
                *sorted(reasons),
            ],
        )
