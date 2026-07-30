from __future__ import annotations

from datetime import timedelta

from psycopg.types.json import Jsonb

from typing import TYPE_CHECKING

from app.models import IncidentCandidate, NormalizedAlert, StoredAnomalyCandidate

if TYPE_CHECKING:
    from app.prometheus_collector import AnomalyCandidate


async def upsert_anomaly_candidates(conn, candidates: list["AnomalyCandidate"]) -> None:
    """Persist only candidate/anomaly signals, not every normal collection point."""
    async with conn.cursor() as cur:
        for candidate in candidates:
            evaluation = candidate.evaluation
            await cur.execute(
                """insert into operations.anomalies (
                       metric_id, subject_type, subject_key, labels, evaluated_at,
                       status, current_value, baseline, z_score, mad_score,
                       change_rate, breached_checks, consecutive_breaches,
                       required_consecutive_windows, event_count
                   ) values (
                       %(metric_id)s, %(subject_type)s, %(subject_key)s, %(labels)s,
                       %(evaluated_at)s, %(status)s, %(current_value)s, %(baseline)s,
                       %(z_score)s, %(mad_score)s, %(change_rate)s,
                       %(breached_checks)s, %(consecutive_breaches)s,
                       %(required_consecutive_windows)s, %(event_count)s
                   ) on conflict (metric_id, subject_key, evaluated_at) do update set
                       labels = excluded.labels,
                       status = excluded.status,
                       current_value = excluded.current_value,
                       baseline = excluded.baseline,
                       z_score = excluded.z_score,
                       mad_score = excluded.mad_score,
                       change_rate = excluded.change_rate,
                       breached_checks = excluded.breached_checks,
                       consecutive_breaches = excluded.consecutive_breaches,
                       required_consecutive_windows = excluded.required_consecutive_windows,
                       event_count = excluded.event_count,
                       updated_at = now()""",
                {
                    "metric_id": candidate.metric_id,
                    "subject_type": candidate.subject_type,
                    "subject_key": candidate.subject_key,
                    "labels": Jsonb(candidate.labels),
                    "evaluated_at": candidate.evaluated_at,
                    "status": candidate.status,
                    "current_value": candidate.current_value,
                    "baseline": (
                        Jsonb(evaluation.baseline.model_dump(mode="json"))
                        if evaluation is not None
                        else None
                    ),
                    "z_score": evaluation.z_score if evaluation else None,
                    "mad_score": evaluation.mad_score if evaluation else None,
                    "change_rate": evaluation.change_rate if evaluation else None,
                    "breached_checks": Jsonb(
                        evaluation.breached_checks if evaluation else []
                    ),
                    "consecutive_breaches": (
                        evaluation.consecutive_breaches if evaluation else 1
                    ),
                    "required_consecutive_windows": (
                        evaluation.required_consecutive_windows if evaluation else 1
                    ),
                    "event_count": candidate.event_count,
                },
            )


async def get_incident(conn, incident_id: str) -> IncidentCandidate | None:
    async with conn.cursor() as cur:
        await cur.execute(
            """select incident_id, status, title, first_seen_at, last_seen_at,
                      earliest_alert_id, earliest_alert_name,
                      suspected_origin_service, affected_services, alert_count,
                      grouping_reasons, alerts
               from operations.incidents
               where incident_id = %s""",
            (incident_id,),
        )
        rows = await cur.fetchall()
        return IncidentCandidate.model_validate(rows[0]) if rows else None


async def list_anomalies_for_incident_window(
    conn,
    *,
    start_at,
    end_at,
) -> list[StoredAnomalyCandidate]:
    async with conn.cursor() as cur:
        await cur.execute(
            """select metric_id, subject_type, subject_key, labels, evaluated_at,
                      status, current_value, baseline, z_score, mad_score,
                      change_rate, breached_checks, consecutive_breaches,
                      required_consecutive_windows, event_count
               from operations.anomalies
               where evaluated_at between %s and %s
               order by evaluated_at, metric_id, subject_key""",
            (start_at, end_at),
        )
        return [StoredAnomalyCandidate.model_validate(row) for row in await cur.fetchall()]


async def upsert_incident_evidence_links(conn, incident_id: str, package) -> None:
    """Keep the deterministic evidence selection auditable without copying telemetry."""
    async with conn.cursor() as cur:
        for anomaly in package.anomalies:
            evidence_id = f"{anomaly.metric_id}:{anomaly.subject_key}:{anomaly.evaluated_at.isoformat()}"
            await cur.execute(
                """insert into operations.incident_evidence (
                       incident_id, evidence_type, evidence_id, selection_reasons
                   ) values (%s, 'anomaly', %s, %s)
                   on conflict (incident_id, evidence_type, evidence_id) do update set
                       selection_reasons = excluded.selection_reasons,
                       updated_at = now()""",
                (incident_id, evidence_id, Jsonb(anomaly.selection_reasons)),
            )
        for alert in package.alerts:
            await cur.execute(
                """insert into operations.incident_evidence (
                       incident_id, evidence_type, evidence_id, selection_reasons
                   ) values (%s, 'alert', %s, %s)
                   on conflict (incident_id, evidence_type, evidence_id) do update set
                       selection_reasons = excluded.selection_reasons,
                       updated_at = now()""",
                (incident_id, alert.alert_id, Jsonb(["incident_alert_group"])),
            )


async def upsert_alerts(conn, alerts: list[NormalizedAlert]) -> None:
    """Persist Alertmanager alerts idempotently; webhook retries update the row."""
    async with conn.cursor() as cur:
        for alert in alerts:
            await cur.execute(
                """insert into operations.alerts (
                       alert_id, source, status, alert_name, service, severity,
                       starts_at, ends_at, received_at, pod, container,
                       labels, annotations, generator_url
                   ) values (
                       %(alert_id)s, %(source)s, %(status)s, %(alert_name)s, %(service)s,
                       %(severity)s, %(starts_at)s, %(ends_at)s, %(received_at)s, %(pod)s,
                       %(container)s, %(labels)s, %(annotations)s, %(generator_url)s
                   ) on conflict (alert_id) do update set
                       status = excluded.status,
                       ends_at = coalesce(excluded.ends_at, operations.alerts.ends_at),
                       received_at = excluded.received_at,
                       pod = excluded.pod,
                       container = excluded.container,
                       labels = excluded.labels,
                       annotations = excluded.annotations,
                       generator_url = excluded.generator_url,
                       updated_at = now()""",
                {
                    **alert.model_dump(),
                    "labels": Jsonb(alert.labels),
                    "annotations": Jsonb(alert.annotations),
                },
            )


async def list_nearby_firing_alerts(
    conn,
    alerts: list[NormalizedAlert],
    time_window_minutes: int,
) -> list[NormalizedAlert]:
    """Load persisted firing alerts that can join an incoming alert group."""
    window = timedelta(minutes=time_window_minutes)
    starts_at = min(alert.starts_at for alert in alerts) - window
    ends_at = max(alert.starts_at for alert in alerts) + window
    async with conn.cursor() as cur:
        await cur.execute(
            """select alert_id, source, status, alert_name, service, severity,
                      starts_at, ends_at, received_at, pod, container,
                      labels, annotations, generator_url
               from operations.alerts
               where status = 'firing' and starts_at between %s and %s
               order by starts_at, alert_id""",
            (starts_at, ends_at),
        )
        return [NormalizedAlert.model_validate(row) for row in await cur.fetchall()]


async def upsert_incidents(conn, incidents: list[IncidentCandidate]) -> None:
    """Create or refresh Incident candidates produced from persisted alerts."""
    async with conn.cursor() as cur:
        for incident in incidents:
            await cur.execute(
                """insert into operations.incidents (
                       incident_id, status, title, first_seen_at, last_seen_at,
                       earliest_alert_id, earliest_alert_name,
                       suspected_origin_service, affected_services, alert_count,
                       grouping_reasons, alerts
                   ) values (
                       %(incident_id)s, %(status)s, %(title)s, %(first_seen_at)s,
                       %(last_seen_at)s, %(earliest_alert_id)s,
                       %(earliest_alert_name)s, %(suspected_origin_service)s,
                       %(affected_services)s, %(alert_count)s, %(grouping_reasons)s,
                       %(alerts)s
                   ) on conflict (incident_id) do update set
                       status = excluded.status,
                       title = excluded.title,
                       last_seen_at = excluded.last_seen_at,
                       earliest_alert_name = excluded.earliest_alert_name,
                       suspected_origin_service = excluded.suspected_origin_service,
                       affected_services = excluded.affected_services,
                       alert_count = excluded.alert_count,
                       grouping_reasons = excluded.grouping_reasons,
                       alerts = excluded.alerts,
                       updated_at = now()""",
                {
                    **incident.model_dump(exclude={"alerts"}),
                    "affected_services": Jsonb(incident.affected_services),
                    "grouping_reasons": Jsonb(incident.grouping_reasons),
                    "alerts": Jsonb(
                        [alert.model_dump(mode="json") for alert in incident.alerts]
                    ),
                },
            )
