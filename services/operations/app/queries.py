from __future__ import annotations

from datetime import timedelta

from psycopg.types.json import Jsonb

from app.models import IncidentCandidate, NormalizedAlert


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
