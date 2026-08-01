from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.models import (
    EvidenceAnomaly,
    EvidencePackage,
    EvidenceSourceStatus,
    IncidentCandidate,
    StoredAnomalyCandidate,
)


@dataclass(frozen=True)
class EvidenceSelection:
    anomaly: EvidenceAnomaly


class EvidenceBuilder:
    """Select deterministic incident evidence before any LLM interpretation."""

    def __init__(self, time_window_minutes: int = 15) -> None:
        self._time_window = timedelta(minutes=time_window_minutes)

    def time_window(self, incident: IncidentCandidate) -> tuple[datetime, datetime]:
        return (
            incident.first_seen_at - self._time_window,
            incident.last_seen_at + self._time_window,
        )

    def build(
        self,
        incident: IncidentCandidate,
        anomalies: list[StoredAnomalyCandidate],
        *,
        generated_at: datetime | None = None,
    ) -> EvidencePackage:
        window_start, window_end = self.time_window(incident)
        selected = [
            selection.anomaly
            for anomaly in anomalies
            if (selection := self._select_anomaly(incident, anomaly)) is not None
        ]
        selected.sort(key=lambda item: (item.evaluated_at, item.metric_id, item.subject_key))

        return EvidencePackage(
            incident=incident,
            generated_at=generated_at or datetime.now(timezone.utc),
            selection_window_start=window_start,
            selection_window_end=window_end,
            anomalies=selected,
            alerts=incident.alerts,
            unavailable_sources=[
                EvidenceSourceStatus(
                    source="logs",
                    message="Loki evidence collector is not connected yet.",
                ),
                EvidenceSourceStatus(
                    source="traces",
                    message="Tempo evidence collector is not connected yet.",
                ),
                EvidenceSourceStatus(
                    source="kubernetes_events",
                    message="Kubernetes event collector is not connected yet.",
                ),
                EvidenceSourceStatus(
                    source="deployments",
                    message="Deployment history collector is not connected yet.",
                ),
            ],
        )

    def _select_anomaly(
        self, incident: IncidentCandidate, anomaly: StoredAnomalyCandidate
    ) -> EvidenceSelection | None:
        window_start, window_end = self.time_window(incident)
        if not window_start <= anomaly.evaluated_at <= window_end:
            return None

        services = set(incident.affected_services)
        services.add(incident.suspected_origin_service)
        labels = anomaly.labels
        reasons: list[str] = ["incident_time_window"]

        service = labels.get("service")
        if service in services:
            reasons.append("same_service")
        elif anomaly.subject_type == "service" and anomaly.subject_key in services:
            reasons.append("same_service")
        elif labels.get("container") in services:
            reasons.append("same_container")
        elif self._matches_incident_pod(labels.get("pod"), services):
            reasons.append("service_pod_prefix")
        else:
            return None

        return EvidenceSelection(
            anomaly=EvidenceAnomaly(
                **anomaly.model_dump(),
                selection_reasons=reasons,
            )
        )

    @staticmethod
    def _matches_incident_pod(pod: str | None, services: set[str]) -> bool:
        return bool(pod) and any(pod.startswith(f"mp-{service}-") for service in services)
