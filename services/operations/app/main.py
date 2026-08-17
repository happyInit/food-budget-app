from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, status
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel

from app.alert_normalizer import AlertNormalizer
from app.anomaly_analyzer import AnomalyAnalyzer
from app.chat_contract import (
    ChatProviderError,
    ChatRequest,
    ChatResponse,
    build_bedrock_chat_response,
    build_mock_chat_response,
)
from app.config import Settings
from app.context import AppCtx, get_conn, get_ctx
from app.db import make_pg_pool
from app.evidence_builder import EvidenceBuilder
from app.incident_correlator import IncidentCorrelator
from app.kubernetes_evidence import KubernetesEvidenceCollector
from app.loki_evidence import LokiApiClient, LokiEvidenceCollector
from app.prometheus_client import PrometheusClient
from app.models import (
    AlertIngestionResult,
    AlertmanagerWebhook,
    AnomalyEvaluation,
    CollectorRunResult,
    EvidenceAnomaly,
    EvidencePackage,
    EvidenceSnapshot,
    EvaluationRequest,
    IncidentCorrelationRequest,
    IncidentCorrelationResult,
    IncidentCandidate,
    StoredAnomalyCandidate,
)
from app.prometheus_collector import PrometheusCollector
from app.rca_contract import (
    BedrockRcaError,
    RcaAnalysisRequest,
    RcaAnalysisResponse,
    build_bedrock_rca,
    build_mock_rca,
)
from app.runbook_embeddings import chunk_markdown, embed_chunk, embed_text, search_similar_chunks
from app.tempo_evidence import TempoEvidenceCollector
from app.queries import (
    anomaly_evidence_hash,
    create_incident_evidence_snapshot,
    get_anomaly_for_rca,
    get_cached_anomaly_rca,
    get_incident,
    get_latest_incident_evidence_snapshot,
    list_anomalies,
    list_anomalies_for_incident_window,
    list_incidents,
    list_nearby_firing_alerts,
    list_runbook_chunks,
    save_anomaly_rca,
    upsert_alerts,
    upsert_incident_evidence_links,
    upsert_incidents,
    upsert_runbook_chunks,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    pool = make_pg_pool(settings) if settings.operations_database_enabled else None
    if pool is not None:
        await pool.open()
    app.state.ctx = AppCtx(pool=pool, settings=settings)
    collector = PrometheusCollector(settings=settings, analyzer=_analyzer)
    collector_task = None
    if settings.operations_collector_enabled and pool is not None:
        collector_task = asyncio.create_task(
            collector.run_forever(pool.connection),
            name="operations-prometheus-collector",
        )
    try:
        yield
    finally:
        if collector_task is not None:
            collector_task.cancel()
            try:
                await collector_task
            except asyncio.CancelledError:
                pass
        if pool is not None:
            await pool.close()


app = FastAPI(title="Operations Service", version="0.1.0", lifespan=lifespan)
Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    should_instrument_requests_inprogress=True,
    excluded_handlers=[r"^/metrics$", r"^/health$"],
    inprogress_name="http_requests_inprogress",
    inprogress_labels=True,
).instrument(app).expose(app, include_in_schema=False)

logger = logging.getLogger(__name__)

_analyzer = AnomalyAnalyzer()
_alert_normalizer = AlertNormalizer()
_incident_correlator = IncidentCorrelator()


def get_analyzer() -> AnomalyAnalyzer:
    return _analyzer


def get_alert_normalizer() -> AlertNormalizer:
    return _alert_normalizer


def get_incident_correlator() -> IncidentCorrelator:
    return _incident_correlator


def get_collector(ctx: AppCtx = Depends(get_ctx)) -> PrometheusCollector:
    return PrometheusCollector(settings=ctx.settings, analyzer=_analyzer)


def get_evidence_builder(ctx: AppCtx = Depends(get_ctx)) -> EvidenceBuilder:
    return EvidenceBuilder(ctx.settings.operations_evidence_time_window_minutes)


def get_kubernetes_evidence_collector(
    ctx: AppCtx = Depends(get_ctx),
) -> KubernetesEvidenceCollector | None:
    if not ctx.settings.operations_kubernetes_evidence_enabled:
        return None
    return KubernetesEvidenceCollector(ctx.settings)


def get_loki_evidence_collector(
    ctx: AppCtx = Depends(get_ctx),
) -> LokiEvidenceCollector | None:
    if not ctx.settings.operations_loki_evidence_enabled:
        return None
    return LokiEvidenceCollector(ctx.settings)


def get_tempo_evidence_collector(
    ctx: AppCtx = Depends(get_ctx),
) -> TempoEvidenceCollector | None:
    if not ctx.settings.operations_tempo_evidence_enabled:
        return None
    return TempoEvidenceCollector(ctx.settings)


class AnomalyRcaTarget(BaseModel):
    """Natural key of an Operations anomaly selected in the dashboard."""

    metric_id: str
    subject_key: str
    evaluated_at: datetime


# Some metric_catalog subject_types carry no "container" label at all (e.g.
# postgres_instance only has namespace/pod), so the real container name for
# Loki filtering can't be read off the anomaly. Verified live against Loki:
# every CNPG pod (pg-1, pg-2, ...) runs its logs under container="postgres"
# regardless of pod name — this is the one mapping build_anomaly_rca has
# actually confirmed, not a guess extended to other subject_types.
_KNOWN_CONTAINER_BY_SUBJECT_TYPE = {"postgres_instance": "postgres"}


async def _collect_evidence_safely(source_name: str, coro):
    """A down evidence source must not crash the whole RCA request.

    EvidencePackage.unavailable_sources already exists to represent "this
    source was never even attempted" (collector disabled in settings), but
    that path only covered the collector being absent — not the collector
    being present and configured, then failing to connect. Confirmed live
    (2026-08-17): Loki OOM-crashlooping under a load test turned an ordinary
    incident RCA request into an unhandled httpx.ConnectError and a 500,
    even though the whole point of unavailable_sources is that a missing
    evidence source should degrade the report, not break the request.
    """
    try:
        return await coro
    except httpx.HTTPError:
        logger.warning(
            "evidence source unreachable, continuing without it",
            extra={"source": source_name},
        )
        return None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "operations"}


@app.post(
    "/internal/anomalies/evaluate",
    response_model=AnomalyEvaluation,
)
async def evaluate_anomaly(
    request: EvaluationRequest,
    analyzer: AnomalyAnalyzer = Depends(get_analyzer),
) -> AnomalyEvaluation:
    return analyzer.evaluate(request)


@app.post(
    "/internal/alerts/alertmanager",
    response_model=AlertIngestionResult,
)
async def ingest_alertmanager_webhook(
    payload: AlertmanagerWebhook,
    normalizer: AlertNormalizer = Depends(get_alert_normalizer),
    correlator: IncidentCorrelator = Depends(get_incident_correlator),
    conn=Depends(get_conn),
) -> AlertIngestionResult:
    normalized = normalizer.normalize(payload)
    await upsert_alerts(conn, normalized.alerts)

    nearby_alerts = await list_nearby_firing_alerts(
        conn,
        normalized.alerts,
        time_window_minutes=15,
    )
    correlation = (
        correlator.correlate(IncidentCorrelationRequest(alerts=nearby_alerts))
        if nearby_alerts
        else IncidentCorrelationResult(incident_count=0, incidents=[])
    )
    await upsert_incidents(conn, correlation.incidents)

    return AlertIngestionResult(
        **normalized.model_dump(exclude={"incident_count", "incidents"}),
        incident_count=correlation.incident_count,
        incidents=correlation.incidents,
    )


@app.post(
    "/internal/incidents/correlate",
    response_model=IncidentCorrelationResult,
)
async def correlate_incidents(
    request: IncidentCorrelationRequest,
    correlator: IncidentCorrelator = Depends(get_incident_correlator),
) -> IncidentCorrelationResult:
    return correlator.correlate(request)


@app.post("/internal/collector/run", response_model=CollectorRunResult)
async def run_prometheus_collector(
    collector: PrometheusCollector = Depends(get_collector),
    conn=Depends(get_conn),
) -> CollectorRunResult:
    """Internal manual trigger for deployment verification and controlled backfills."""
    result = await collector.collect_once(conn)
    return CollectorRunResult(**result.__dict__)


@app.post("/internal/runbooks/ingest")
async def ingest_runbooks(
    ctx: AppCtx = Depends(get_ctx),
    conn=Depends(get_conn),
) -> dict:
    """Chunk + embed the bundled runbook corpus, upsert into operations.runbook_chunks.

    Idempotent per source file (chunk_id is deterministic) — safe to re-run
    after editing a runbook or adding a new one to app/runbooks/.
    """
    from pathlib import Path

    runbooks_dir = Path(__file__).resolve().parent / "runbooks"
    ingested = 0
    per_file: dict[str, int] = {}
    for path in sorted(runbooks_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        chunks = chunk_markdown(text, source_path=path.name)
        embedded = [
            embed_chunk(
                chunk,
                region_name=ctx.settings.aws_region,
                model_id=ctx.settings.operations_embedding_model_id,
            )
            for chunk in chunks
        ]
        await upsert_runbook_chunks(conn, embedded)
        per_file[path.name] = len(embedded)
        ingested += len(embedded)
    return {"ingested_chunks": ingested, "per_file": per_file}


@app.get("/internal/runbooks/search")
async def search_runbooks(
    query: str,
    top_k: int = Query(default=5, ge=1, le=20),
    ctx: AppCtx = Depends(get_ctx),
    conn=Depends(get_conn),
) -> list[dict]:
    """Embed the query and rank the stored runbook corpus by cosine similarity."""
    query_embedding = embed_text(
        query,
        region_name=ctx.settings.aws_region,
        model_id=ctx.settings.operations_embedding_model_id,
    )
    rows = await list_runbook_chunks(conn)
    by_id = {row["chunk_id"]: row for row in rows}
    candidates = [(row["chunk_id"], row["embedding"]) for row in rows]
    ranked = search_similar_chunks(query_embedding, candidates, top_k=top_k)
    return [
        {
            "chunk_id": chunk_id,
            "score": score,
            "source_path": by_id[chunk_id]["source_path"],
            "title": by_id[chunk_id]["title"],
            "content": by_id[chunk_id]["content"],
        }
        for chunk_id, score in ranked
    ]


@app.get("/internal/anomalies", response_model=list[StoredAnomalyCandidate])
async def get_anomalies(
    start_at: datetime,
    end_at: datetime,
    limit: int = Query(default=100, ge=1, le=500),
    conn=Depends(get_conn),
) -> list[StoredAnomalyCandidate]:
    return await list_anomalies(
        conn,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
    )


@app.get("/internal/incidents", response_model=list[IncidentCandidate])
async def get_incidents(
    start_at: datetime,
    end_at: datetime,
    limit: int = Query(default=100, ge=1, le=500),
    conn=Depends(get_conn),
) -> list[IncidentCandidate]:
    return await list_incidents(
        conn,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
    )


@app.post(
    "/internal/incidents/{incident_id}/evidence",
    response_model=EvidencePackage,
)
async def build_incident_evidence_package(
    incident_id: str,
    builder: EvidenceBuilder = Depends(get_evidence_builder),
    kubernetes_collector: KubernetesEvidenceCollector | None = Depends(
        get_kubernetes_evidence_collector
    ),
    loki_collector: LokiEvidenceCollector | None = Depends(get_loki_evidence_collector),
    tempo_collector: TempoEvidenceCollector | None = Depends(get_tempo_evidence_collector),
    conn=Depends(get_conn),
) -> EvidencePackage:
    incident = await get_incident(conn, incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="incident was not found",
        )
    return await _build_and_persist_incident_evidence(
        conn,
        incident,
        builder=builder,
        kubernetes_collector=kubernetes_collector,
        loki_collector=loki_collector,
        tempo_collector=tempo_collector,
    )


async def _build_and_persist_incident_evidence(
    conn,
    incident: IncidentCandidate,
    *,
    builder: EvidenceBuilder,
    kubernetes_collector: KubernetesEvidenceCollector | None,
    loki_collector: LokiEvidenceCollector | None,
    tempo_collector: TempoEvidenceCollector | None,
) -> EvidencePackage:
    start_at, end_at = builder.time_window(incident)
    anomalies = await list_anomalies_for_incident_window(
        conn,
        start_at=start_at,
        end_at=end_at,
    )
    kubernetes_evidence = None
    if kubernetes_collector is not None:
        kubernetes_evidence = await _collect_evidence_safely(
            "kubernetes",
            kubernetes_collector.collect(incident, start_at=start_at, end_at=end_at),
        )
    logs = (
        await _collect_evidence_safely(
            "loki", loki_collector.collect(incident, start_at=start_at, end_at=end_at)
        )
        if loki_collector is not None
        else None
    )
    traces = (
        await _collect_evidence_safely(
            "tempo", tempo_collector.collect(incident, start_at=start_at, end_at=end_at)
        )
        if tempo_collector is not None
        else None
    )
    package = builder.build(
        incident,
        anomalies,
        logs=logs,
        traces=traces,
        kubernetes_events=(kubernetes_evidence.events if kubernetes_evidence else None),
        deployments=(kubernetes_evidence.deployments if kubernetes_evidence else None),
    )
    await upsert_incident_evidence_links(conn, incident.incident_id, package)
    await create_incident_evidence_snapshot(conn, package)
    return package


@app.get(
    "/internal/incidents/{incident_id}/evidence/latest",
    response_model=EvidenceSnapshot,
)
async def get_latest_evidence_snapshot(
    incident_id: str,
    conn=Depends(get_conn),
) -> EvidenceSnapshot:
    snapshot = await get_latest_incident_evidence_snapshot(conn, incident_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="incident evidence snapshot was not found",
        )
    return snapshot


@app.post(
    "/internal/incidents/{incident_id}/rca",
    response_model=RcaAnalysisResponse,
)
async def build_incident_rca(
    incident_id: str,
    ctx: AppCtx = Depends(get_ctx),
    builder: EvidenceBuilder = Depends(get_evidence_builder),
    kubernetes_collector: KubernetesEvidenceCollector | None = Depends(
        get_kubernetes_evidence_collector
    ),
    loki_collector: LokiEvidenceCollector | None = Depends(get_loki_evidence_collector),
    tempo_collector: TempoEvidenceCollector | None = Depends(get_tempo_evidence_collector),
    conn=Depends(get_conn),
) -> RcaAnalysisResponse:
    """Generate an RCA draft from the incident's latest Evidence snapshot.

    Builds a fresh Evidence snapshot first if none exists yet — the dashboard
    button that triggers this is the operator's *only* action, and requiring
    a separate manual "build evidence" call first (previously: 404 telling
    them to go do that) was pure friction, not an intentional safety gate.
    An existing snapshot is still reused rather than rebuilt every call, so a
    second RCA request the same investigation is still evidence-stable.

    The selected provider is explicit so the dashboard never mistakes a mock
    draft for a Bedrock investigation result.
    """
    snapshot = await get_latest_incident_evidence_snapshot(conn, incident_id)
    if snapshot is None:
        incident = await get_incident(conn, incident_id)
        if incident is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="incident was not found",
            )
        package = await _build_and_persist_incident_evidence(
            conn,
            incident,
            builder=builder,
            kubernetes_collector=kubernetes_collector,
            loki_collector=loki_collector,
            tempo_collector=tempo_collector,
        )
    else:
        package = snapshot.package
    request = RcaAnalysisRequest(evidence=package)
    if ctx.settings.operations_rca_provider == "mock":
        return build_mock_rca(request)
    try:
        return await asyncio.to_thread(
            build_bedrock_rca,
            request,
            region_name=ctx.settings.aws_region,
            model_id=ctx.settings.bedrock_model_id,
            guardrail_id=ctx.settings.operations_guardrail_id or None,
            guardrail_version=ctx.settings.operations_guardrail_version or None,
        )
    except BedrockRcaError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@app.post(
    "/internal/anomalies/rca",
    response_model=RcaAnalysisResponse,
)
async def build_anomaly_rca(
    target: AnomalyRcaTarget,
    ctx: AppCtx = Depends(get_ctx),
    builder: EvidenceBuilder = Depends(get_evidence_builder),
    kubernetes_collector: KubernetesEvidenceCollector | None = Depends(
        get_kubernetes_evidence_collector
    ),
    loki_collector: LokiEvidenceCollector | None = Depends(get_loki_evidence_collector),
    tempo_collector: TempoEvidenceCollector | None = Depends(get_tempo_evidence_collector),
    conn=Depends(get_conn),
) -> RcaAnalysisResponse:
    """Generate a Bedrock RCA draft directly from one persisted anomaly.

    Incident correlation is useful when Alertmanager has grouped several
    alerts, but it is not a prerequisite for investigating one anomaly.
    Values are always re-read from Operations DB; the browser only supplies
    the anomaly's natural key.
    """
    anomaly = await get_anomaly_for_rca(
        conn,
        metric_id=target.metric_id,
        subject_key=target.subject_key,
        evaluated_at=target.evaluated_at,
    )
    if anomaly is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="selected anomaly was not found in Operations DB",
        )
    service = anomaly.labels.get("service") or anomaly.subject_key.rsplit("/", 1)[-1]
    scope_id = f"anomaly:{anomaly.metric_id}:{anomaly.subject_key}:{anomaly.evaluated_at.isoformat()}"
    synthetic_incident = IncidentCandidate(
        incident_id=scope_id,
        title=f"Anomaly RCA · {anomaly.subject_key} · {anomaly.metric_id}",
        first_seen_at=anomaly.evaluated_at,
        last_seen_at=anomaly.evaluated_at,
        earliest_alert_id="anomaly-only",
        earliest_alert_name="Anomaly-only RCA",
        suspected_origin_service=service,
        affected_services=[service],
        alert_count=0,
        grouping_reasons=["direct_anomaly_investigation"],
        alerts=[],
    )
    start_at, end_at = builder.time_window(synthetic_incident)
    kubernetes_evidence = (
        await _collect_evidence_safely(
            "kubernetes",
            kubernetes_collector.collect(synthetic_incident, start_at=start_at, end_at=end_at),
        )
        if kubernetes_collector is not None else None
    )
    # Data-tier anomalies (pg-2 in namespace "data") have neither their real
    # namespace nor container name derivable from affected_services=["pg-2"]
    # alone — operations_kubernetes_namespace defaults to "app", so without
    # this the Loki query silently searches the wrong namespace entirely.
    # container isn't in every metric's labels (e.g. postgres_connection_ratio
    # only carries namespace/pod), so pod is included as a best-effort second
    # candidate rather than requiring an exact container name.
    logs = await _collect_evidence_safely(
        "loki",
        loki_collector.collect(
            synthetic_incident,
            start_at=start_at,
            end_at=end_at,
            namespace=anomaly.labels.get("namespace"),
            extra_containers={
                value
                for value in (
                    anomaly.labels.get("container"),
                    anomaly.labels.get("pod"),
                    _KNOWN_CONTAINER_BY_SUBJECT_TYPE.get(anomaly.subject_type),
                )
                if value
            },
        ),
    ) if loki_collector else None
    traces = await _collect_evidence_safely(
        "tempo", tempo_collector.collect(synthetic_incident, start_at=start_at, end_at=end_at)
    ) if tempo_collector else None
    evidence = builder.build(
        synthetic_incident, [anomaly], logs=logs, traces=traces,
        kubernetes_events=(kubernetes_evidence.events if kubernetes_evidence else None),
        deployments=(kubernetes_evidence.deployments if kubernetes_evidence else None),
    )
    # EvidenceBuilder._select_anomaly() only keeps anomalies whose labels match
    # an "mp-<service>-..." app-tier naming pattern — it silently drops
    # everything else (data tier: pg/es/redis subject_keys like "data/pg-2").
    # That filter exists to correlate *other* co-occurring anomalies into an
    # alert-driven incident; it was never meant to gate the one anomaly the
    # caller is directly investigating here, which must always be present.
    if not any(
        item.metric_id == anomaly.metric_id
        and item.subject_key == anomaly.subject_key
        and item.evaluated_at == anomaly.evaluated_at
        for item in evidence.anomalies
    ):
        evidence = evidence.model_copy(
            update={
                "anomalies": [
                    EvidenceAnomaly(
                        **anomaly.model_dump(), selection_reasons=["direct_anomaly_investigation"]
                    ),
                    *evidence.anomalies,
                ]
            }
        )
    request = RcaAnalysisRequest(evidence=evidence)
    if ctx.settings.operations_rca_provider == "mock":
        return build_mock_rca(request)
    evidence_hash = anomaly_evidence_hash(request.evidence)
    cached = await get_cached_anomaly_rca(
        conn,
        metric_id=anomaly.metric_id,
        subject_key=anomaly.subject_key,
        evaluated_at=anomaly.evaluated_at,
        evidence_hash=evidence_hash,
    )
    if cached is not None:
        return RcaAnalysisResponse.model_validate({**cached, "cached": True})
    try:
        response = await asyncio.to_thread(
            build_bedrock_rca,
            request,
            region_name=ctx.settings.aws_region,
            model_id=ctx.settings.bedrock_model_id,
            guardrail_id=ctx.settings.operations_guardrail_id or None,
            guardrail_version=ctx.settings.operations_guardrail_version or None,
        )
        await save_anomaly_rca(
            conn,
            metric_id=anomaly.metric_id,
            subject_key=anomaly.subject_key,
            evaluated_at=anomaly.evaluated_at,
            evidence_hash=evidence_hash,
            response=response.model_dump(mode="json"),
        )
        return response
    except BedrockRcaError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


# Aggregate, unlabeled variants of the same PromQL already registered per-service
# in metric_catalog.py (service_request_rate/service_5xx_rate/pod_cpu_usage/
# pod_memory_working_set). Deliberately not imported from there — the catalog
# entries are scoped `by(service)`/`by(namespace, pod, container)` for the
# Analyzer; the chat snapshot wants one cluster-wide number per signal instead.
_CHAT_SNAPSHOT_PROMQL = {
    "request_rate_per_second": 'sum(rate(http_request_duration_highr_seconds_count{namespace="app"}[5m]))',
    "error_rate_percent": (
        "(100 * (sum(rate(http_requests_total{namespace=\"app\", status=~\"5..\"}[5m])) "
        "or vector(0)) / (sum(rate(http_requests_total{namespace=\"app\"}[5m])) or vector(1)))"
    ),
    "cpu_cores_used": (
        "sum(rate(container_cpu_usage_seconds_total{namespace=~\"app|data|pipeline\", "
        "container!=\"\", container!=\"POD\", container!=\"istio-proxy\", image!=\"\"}[5m]))"
    ),
    "memory_bytes_used": (
        "sum(container_memory_working_set_bytes{namespace=~\"app|data|pipeline\", "
        "container!=\"\", container!=\"POD\", container!=\"istio-proxy\", image!=\"\"})"
    ),
}

_CHAT_LOG_ERROR_QUERY = '{namespace=~"app|data|pipeline"} |~ "(?i)error|exception|traceback|fatal|panic"'


async def _gather_chat_prometheus(settings: Settings) -> dict:
    client = PrometheusClient(settings.operations_prometheus_url)
    now = datetime.now(timezone.utc)
    values: dict[str, float | None] = {}
    try:
        for name, promql in _CHAT_SNAPSHOT_PROMQL.items():
            series = await client.query(promql, at=now)
            values[name] = series[0].points[0].value if series and series[0].points else None
    except Exception:
        return {"available": False, "reason": "Prometheus 조회 실패(연결 확인 필요)"}
    return {"available": True, **values}


async def _gather_chat_logs(settings: Settings) -> dict:
    if not settings.operations_loki_evidence_enabled:
        return {"available": False, "reason": "Loki 연동이 비활성 상태(OPERATIONS_LOKI_EVIDENCE_ENABLED=false)"}
    client = LokiApiClient(settings)
    now = datetime.now(timezone.utc)
    try:
        streams = await client.query_range(
            _CHAT_LOG_ERROR_QUERY,
            start_at=now - timedelta(minutes=15),
            end_at=now,
            limit=200,
        )
    except Exception:
        return {"available": False, "reason": "Loki 조회 실패(연결 확인 필요)"}
    error_log_count = sum(len(stream.get("values", [])) for stream in streams)
    return {"available": True, "window_minutes": 15, "error_or_warn_log_count": error_log_count}


async def gather_chat_snapshot(ctx: AppCtx, conn) -> dict:
    """Best-effort current-status bundle for the dashboard chat assistant.

    Each source degrades independently — a dead Prometheus port-forward must
    not block anomaly/incident data from reaching the model. The model is
    told explicitly which sources are unavailable (chat_prompt.SYSTEM_PROMPT)
    so it says "수집되지 않았습니다" instead of guessing.
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=15)
    anomalies = await list_anomalies(conn, start_at=window_start, end_at=now, limit=200)
    incidents = await list_incidents(conn, start_at=window_start, end_at=now, limit=50)
    active_anomalies = [a for a in anomalies if a.status == "anomaly"]
    return {
        "window_minutes": 15,
        "metrics": await _gather_chat_prometheus(ctx.settings),
        "logs": await _gather_chat_logs(ctx.settings),
        "active_anomalies": [
            {"metric_id": a.metric_id, "subject_key": a.subject_key, "current_value": a.current_value}
            for a in active_anomalies
        ],
        "active_anomaly_count": len(active_anomalies),
        "open_incidents": [
            {
                "incident_id": i.incident_id,
                "title": i.title,
                "suspected_origin_service": i.suspected_origin_service,
                "affected_services": i.affected_services,
            }
            for i in incidents
        ],
        "open_incident_count": len(incidents),
    }


@app.post("/internal/chat", response_model=ChatResponse)
async def chat_with_dashboard_assistant(
    payload: ChatRequest,
    ctx: AppCtx = Depends(get_ctx),
    conn=Depends(get_conn),
) -> ChatResponse:
    """Answer an ad-hoc operator question using a fresh current-status snapshot.

    Distinct from /rca: this is not an incident investigation. It always
    gathers its own snapshot server-side (ignores any snapshot the caller
    sends) so the browser cannot spoof "정상입니다" by fabricating client-side
    data — same distrust-the-client principle as the rest of Operations AI.
    """
    snapshot = await gather_chat_snapshot(ctx, conn)
    request = ChatRequest(question=payload.question, snapshot=snapshot)
    if ctx.settings.operations_chat_provider == "mock":
        return build_mock_chat_response(request)
    try:
        return build_bedrock_chat_response(
            request,
            region_name=ctx.settings.aws_region,
            model_id=ctx.settings.bedrock_model_id,
            guardrail_id=ctx.settings.operations_guardrail_id or None,
            guardrail_version=ctx.settings.operations_guardrail_version or None,
        )
    except ChatProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"chat provider failed: {exc}",
        ) from exc
