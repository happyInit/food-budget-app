from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings
from app.models import IncidentCandidate, LogPatternEvidence

_ERROR_FILTER = '|~ "(?i)error|exception|traceback|fatal|panic"'
_UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_NUMBER_PATTERN = re.compile(r"\d+")


def normalize_log_pattern(line: str) -> str:
    """Collapse variable parts of a log line into a stable pattern key.

    UUIDs are masked before numbers because a UUID also contains digits.
    """
    normalized = _UUID_PATTERN.sub("<uuid>", line)
    normalized = _NUMBER_PATTERN.sub("#", normalized)
    return normalized


@dataclass(frozen=True)
class _PatternGroup:
    namespace: str
    container: str
    pattern: str
    count: int
    first_seen_at: datetime
    last_seen_at: datetime
    samples: list[str]


class LokiApiClient:
    """Small read-only Loki query client used only for incident evidence."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    async def query_range(
        self,
        query: str,
        *,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        params = {
            "query": query,
            "start": str(int(start_at.timestamp() * 1_000_000_000)),
            "end": str(int(end_at.timestamp() * 1_000_000_000)),
            "limit": limit,
            "direction": "backward",
        }
        if self._client is not None:
            response = await self._client.get("/loki/api/v1/query_range", params=params)
        else:
            async with httpx.AsyncClient(
                base_url=self._settings.operations_loki_url,
                timeout=self._settings.operations_loki_query_timeout_seconds,
            ) as client:
                response = await client.get("/loki/api/v1/query_range", params=params)
        response.raise_for_status()
        payload = response.json()
        return payload.get("data", {}).get("result", [])


class LokiEvidenceCollector:
    """Collect aggregated error log patterns for one Incident's services."""

    def __init__(self, settings: Settings, client: LokiApiClient | None = None) -> None:
        self._settings = settings
        self._client = client or LokiApiClient(settings)

    async def collect(
        self,
        incident: IncidentCandidate,
        *,
        start_at: datetime,
        end_at: datetime,
        namespace: str | None = None,
        extra_containers: set[str] | None = None,
    ) -> list[LogPatternEvidence]:
        """Collect error log patterns for the incident's services.

        ``namespace``/``extra_containers`` are overrides for callers outside
        the "app" namespace, alert-driven incident flow this collector was
        originally built for (see app.main.build_anomaly_rca) — a data-tier
        anomaly (e.g. pg-2 in namespace "data") has neither its namespace nor
        its actual container name ("postgres") derivable from
        incident.affected_services alone, so the caller supplies them from
        the anomaly's own labels instead of the operations_kubernetes_namespace
        default(which is scoped to the app tier).
        """
        services = {incident.suspected_origin_service, *incident.affected_services}
        if extra_containers:
            services |= extra_containers
        namespace = namespace or self._settings.operations_kubernetes_namespace
        container_selector = "|".join(sorted(services))
        query = f'{{namespace="{namespace}", container=~"{container_selector}"}} {_ERROR_FILTER}'

        streams = await self._client.query_range(
            query,
            start_at=start_at,
            end_at=end_at,
            limit=1000,
        )
        groups = self._group_by_pattern(streams)
        return sorted(
            (self._to_evidence(namespace, group) for group in groups),
            key=lambda item: (item.container, item.pattern),
        )

    def _group_by_pattern(self, streams: list[dict[str, Any]]) -> list[_PatternGroup]:
        groups: OrderedDict[tuple[str, str, str], _PatternGroup] = OrderedDict()
        max_samples = self._settings.operations_loki_max_samples_per_pattern

        for stream in streams:
            labels = stream.get("stream", {})
            namespace = labels.get("namespace", "")
            container = labels.get("container", "")
            for entry in stream.get("values", []):
                occurred_at = self._entry_time(entry)
                line = entry[1]
                pattern = normalize_log_pattern(line)
                key = (namespace, container, pattern)

                existing = groups.get(key)
                if existing is None:
                    groups[key] = _PatternGroup(
                        namespace=namespace,
                        container=container,
                        pattern=pattern,
                        count=1,
                        first_seen_at=occurred_at,
                        last_seen_at=occurred_at,
                        samples=[line],
                    )
                    continue

                samples = existing.samples
                if len(samples) < max_samples:
                    samples = [*samples, line]
                groups[key] = _PatternGroup(
                    namespace=existing.namespace,
                    container=existing.container,
                    pattern=existing.pattern,
                    count=existing.count + 1,
                    first_seen_at=min(existing.first_seen_at, occurred_at),
                    last_seen_at=max(existing.last_seen_at, occurred_at),
                    samples=samples,
                )

        return list(groups.values())

    @staticmethod
    def _entry_time(entry: list[str]) -> datetime:
        return datetime.fromtimestamp(int(entry[0]) / 1_000_000_000, tz=timezone.utc)

    @staticmethod
    def _to_evidence(namespace: str, group: _PatternGroup) -> LogPatternEvidence:
        return LogPatternEvidence(
            namespace=group.namespace or namespace,
            container=group.container,
            pattern=group.pattern,
            count=group.count,
            first_seen_at=group.first_seen_at,
            last_seen_at=group.last_seen_at,
            samples=group.samples,
            selection_reasons=["incident_time_window", "incident_service_container"],
        )
