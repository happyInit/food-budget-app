from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import timedelta

from app.models import (
    CorrelationConfig,
    IncidentCandidate,
    IncidentCorrelationRequest,
    IncidentCorrelationResult,
    NormalizedAlert,
)


@dataclass
class _IncidentGroup:
    alerts: list[NormalizedAlert] = field(default_factory=list)
    reasons: set[str] = field(default_factory=set)

    @property
    def first_seen_at(self):
        return min(alert.starts_at for alert in self.alerts)

    @property
    def last_seen_at(self):
        return max(alert.starts_at for alert in self.alerts)


class IncidentCorrelator:
    """Build deterministic Incident candidates from normalized alerts.

    An earliest alert is a starting point for investigation, not a confirmed
    root cause. Bedrock and an engineer assess causality in later phases.
    """

    def correlate(self, request: IncidentCorrelationRequest) -> IncidentCorrelationResult:
        config = request.config
        groups: list[_IncidentGroup] = []

        for alert in sorted(request.alerts, key=lambda item: item.starts_at):
            matching_indexes = [
                index
                for index, group in enumerate(groups)
                if self._matches_group(alert, group, config)
            ]
            if not matching_indexes:
                groups.append(_IncidentGroup(alerts=[alert]))
                continue

            primary_index = matching_indexes[0]
            primary = groups[primary_index]
            primary.reasons.update(self._match_reasons(alert, primary, config))
            primary.alerts.append(alert)

            for index in reversed(matching_indexes[1:]):
                merged = groups.pop(index)
                primary.alerts.extend(merged.alerts)
                primary.reasons.update(merged.reasons)
                primary.reasons.add("bridged_alert")

        incidents = [self._to_candidate(group) for group in groups]
        return IncidentCorrelationResult(
            incident_count=len(incidents),
            incidents=incidents,
        )

    def _matches_group(
        self,
        alert: NormalizedAlert,
        group: _IncidentGroup,
        config: CorrelationConfig,
    ) -> bool:
        return bool(self._match_reasons(alert, group, config))

    def _match_reasons(
        self,
        alert: NormalizedAlert,
        group: _IncidentGroup,
        config: CorrelationConfig,
    ) -> set[str]:
        window = timedelta(minutes=config.time_window_minutes)
        if alert.starts_at - group.last_seen_at > window:
            return set()

        reasons: set[str] = {"time_window"}
        group_services = {item.service for item in group.alerts}
        if alert.service in group_services:
            reasons.add("same_service")
            return reasons

        group_pods = {item.pod for item in group.alerts if item.pod}
        if alert.pod and alert.pod in group_pods:
            reasons.add("same_pod")
            return reasons

        if any(
            self._services_connected(alert.service, service, config)
            for service in group_services
        ):
            reasons.add("service_dependency")
            return reasons

        return set()

    @staticmethod
    def _services_connected(
        first: str,
        second: str,
        config: CorrelationConfig,
    ) -> bool:
        if first == second:
            return True

        adjacency: dict[str, set[str]] = {}
        for dependency in config.dependencies:
            adjacency.setdefault(dependency.upstream, set()).add(dependency.downstream)
            adjacency.setdefault(dependency.downstream, set()).add(dependency.upstream)

        pending = [first]
        visited: set[str] = set()
        while pending:
            service = pending.pop()
            if service == second:
                return True
            if service in visited:
                continue
            visited.add(service)
            pending.extend(adjacency.get(service, set()) - visited)
        return False

    @staticmethod
    def _to_candidate(group: _IncidentGroup) -> IncidentCandidate:
        alerts = sorted(group.alerts, key=lambda item: item.starts_at)
        earliest = alerts[0]
        affected_services = sorted({alert.service for alert in alerts})
        incident_id = _incident_id(alerts)
        return IncidentCandidate(
            incident_id=incident_id,
            title=f"{earliest.service} incident candidate",
            first_seen_at=alerts[0].starts_at,
            last_seen_at=alerts[-1].starts_at,
            earliest_alert_id=earliest.alert_id,
            earliest_alert_name=earliest.alert_name,
            suspected_origin_service=earliest.service,
            affected_services=affected_services,
            alert_count=len(alerts),
            grouping_reasons=sorted(group.reasons),
            alerts=alerts,
        )


def _incident_id(alerts: list[NormalizedAlert]) -> str:
    # Tie-breaking same-starts_at alerts on alert_id is unstable across
    # re-correlation: two Alertmanager alerts sharing one starts_at (routine
    # when several rules fire off the same evaluation) can arrive in
    # separate webhook calls (different alertname => different group_by
    # bucket). Whichever alert_id sorts first flips depending on which
    # alerts happen to be in the group *this time*, so the "earliest" alert
    # — and therefore the incident_id derived from it — could retroactively
    # change once a later-arriving alert with a lexicographically smaller
    # alert_id joins. ON CONFLICT (incident_id) then can't recognize it as
    # the same incident and inserts a duplicate row instead of updating.
    # received_at is immutable once an alert is first persisted (upsert_alerts
    # no longer overwrites it), so it reflects true arrival order rather than
    # an accident of alert_id string comparison — sorting on it first keeps
    # incident_id stable as the group grows.
    earliest_alert = min(
        alerts, key=lambda alert: (alert.starts_at, alert.received_at, alert.alert_id)
    )
    return hashlib.sha256(earliest_alert.alert_id.encode()).hexdigest()[:16]
