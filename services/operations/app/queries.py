from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
import json
from uuid import uuid4

from psycopg.types.json import Jsonb

from typing import TYPE_CHECKING

from app.models import (
    EvidencePackage,
    EvidenceSnapshot,
    IncidentCandidate,
    NormalizedAlert,
    StoredAnomalyCandidate,
)

if TYPE_CHECKING:
    from app.prometheus_collector import AnomalyCandidate
    from app.runbook_embeddings import RunbookChunk


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
                 and status = 'anomaly'
               order by evaluated_at, metric_id, subject_key""",
            (start_at, end_at),
        )
        return [StoredAnomalyCandidate.model_validate(row) for row in await cur.fetchall()]


async def get_anomaly_for_rca(
    conn, *, metric_id: str, subject_key: str, evaluated_at
) -> StoredAnomalyCandidate | None:
    """Read the exact persisted anomaly selected by the dashboard.

    The browser submits only the immutable natural key; all values sent to an
    RCA provider are re-read from Operations DB on the server.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """select metric_id, subject_type, subject_key, labels, evaluated_at,
                      status, current_value, baseline, z_score, mad_score,
                      change_rate, breached_checks, consecutive_breaches,
                      required_consecutive_windows, event_count
               from operations.anomalies
               where metric_id = %s and subject_key = %s and evaluated_at = %s
               limit 1""",
            (metric_id, subject_key, evaluated_at),
        )
        rows = await cur.fetchall()
        return StoredAnomalyCandidate.model_validate(rows[0]) if rows else None


def anomaly_evidence_hash(evidence: EvidencePackage) -> str:
    # generated_at describes when this request was assembled, not a fact the
    # model should re-analyse. Keeping it would defeat cache reuse on every
    # click even when all collected evidence is identical.
    payload = evidence.model_dump(mode="json")
    payload.pop("generated_at", None)
    # Prompt/contract revisions alter the meaning and presentation of an RCA.
    # They must not reuse a result generated under an older instruction set.
    payload["rca_prompt_version"] = "operator-report-v2"
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def get_cached_anomaly_rca(conn, *, metric_id, subject_key, evaluated_at, evidence_hash):
    async with conn.cursor() as cur:
        await cur.execute(
            """select response from operations.anomaly_rca_results
               where metric_id = %s and subject_key = %s and evaluated_at = %s
                 and evidence_hash = %s limit 1""",
            (metric_id, subject_key, evaluated_at, evidence_hash),
        )
        rows = await cur.fetchall()
        return rows[0]["response"] if rows else None


async def save_anomaly_rca(conn, *, metric_id, subject_key, evaluated_at, evidence_hash, response) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into operations.anomaly_rca_results
               (metric_id, subject_key, evaluated_at, evidence_hash, response)
               values (%s, %s, %s, %s, %s)
               on conflict (metric_id, subject_key, evaluated_at, evidence_hash)
               do update set response = excluded.response, created_at = now()""",
            (metric_id, subject_key, evaluated_at, evidence_hash, Jsonb(response)),
        )


async def list_anomalies(
    conn,
    *,
    start_at,
    end_at,
    limit: int,
) -> list[StoredAnomalyCandidate]:
    """Return persisted anomaly signals for a dashboard-selected time range."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select metric_id, subject_type, subject_key, labels, evaluated_at,
                      status, current_value, baseline, z_score, mad_score,
                      change_rate, breached_checks, consecutive_breaches,
                      required_consecutive_windows, event_count
               from operations.anomalies
               where evaluated_at between %s and %s
               order by evaluated_at desc, metric_id, subject_key
               limit %s""",
            (start_at, end_at, limit),
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


async def create_incident_evidence_snapshot(
    conn, package: EvidencePackage
) -> EvidenceSnapshot:
    """Persist one immutable, compact evidence capture for later investigation."""
    snapshot = EvidenceSnapshot(
        snapshot_id=str(uuid4()),
        incident_id=package.incident.incident_id,
        captured_at=package.generated_at,
        package=package,
    )
    async with conn.cursor() as cur:
        await cur.execute(
            """insert into operations.incident_evidence_snapshots (
                   snapshot_id, incident_id, captured_at, evidence_package
               ) values (%s, %s, %s, %s)""",
            (
                snapshot.snapshot_id,
                snapshot.incident_id,
                snapshot.captured_at,
                Jsonb(snapshot.package.model_dump(mode="json")),
            ),
        )
    return snapshot


async def get_latest_incident_evidence_snapshot(
    conn, incident_id: str
) -> EvidenceSnapshot | None:
    async with conn.cursor() as cur:
        await cur.execute(
            """select snapshot_id, incident_id, captured_at,
                      evidence_package as package
               from operations.incident_evidence_snapshots
               where incident_id = %s
               order by captured_at desc, snapshot_id desc
               limit 1""",
            (incident_id,),
        )
        rows = await cur.fetchall()
        return EvidenceSnapshot.model_validate(rows[0]) if rows else None


async def list_incidents(
    conn,
    *,
    start_at,
    end_at,
    limit: int,
) -> list[IncidentCandidate]:
    """Return incidents overlapping a dashboard-selected time range."""
    async with conn.cursor() as cur:
        await cur.execute(
            """select incident_id, status, title, first_seen_at, last_seen_at,
                      earliest_alert_id, earliest_alert_name,
                      suspected_origin_service, affected_services, alert_count,
                      grouping_reasons, alerts
               from operations.incidents
               where first_seen_at <= %s and last_seen_at >= %s
               order by last_seen_at desc, incident_id
               limit %s""",
            (end_at, start_at, limit),
        )
        return [IncidentCandidate.model_validate(row) for row in await cur.fetchall()]


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


async def upsert_runbook_chunks(conn, chunks: list["RunbookChunk"]) -> None:
    """Store or refresh RAG runbook chunks, embedding included.

    Re-ingesting the same source_path is idempotent — chunk_id is derived
    deterministically from source_path + chunk_index (app.runbook_embeddings),
    so re-running ingestion after editing a runbook updates existing rows
    instead of duplicating them.
    """
    async with conn.cursor() as cur:
        for chunk in chunks:
            await cur.execute(
                """insert into operations.runbook_chunks (
                       chunk_id, source_path, chunk_index, title, content,
                       embedding, embedding_model
                   ) values (
                       %(chunk_id)s, %(source_path)s, %(chunk_index)s, %(title)s,
                       %(content)s, %(embedding)s, %(embedding_model)s
                   ) on conflict (chunk_id) do update set
                       source_path = excluded.source_path,
                       chunk_index = excluded.chunk_index,
                       title = excluded.title,
                       content = excluded.content,
                       embedding = excluded.embedding,
                       embedding_model = excluded.embedding_model,
                       updated_at = now()""",
                {
                    "chunk_id": chunk.chunk_id,
                    "source_path": chunk.source_path,
                    "chunk_index": chunk.chunk_index,
                    "title": chunk.title,
                    "content": chunk.content,
                    "embedding": chunk.embedding,
                    "embedding_model": chunk.embedding_model,
                },
            )


async def list_runbook_chunks(conn) -> list[dict]:
    """Fetch all embedded runbook chunks for in-process cosine similarity search.

    No pgvector — this loads the (small) corpus into app memory and ranks it
    there (app.runbook_embeddings.search_similar_chunks). See
    docs/operations-ai-bedrock-guardrail-rag-permission-request.md §4.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """select chunk_id, source_path, chunk_index, title, content, embedding
               from operations.runbook_chunks
               where embedding is not null
               order by source_path, chunk_index"""
        )
        return await cur.fetchall()
