from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query, status
from prometheus_fastapi_instrumentator import Instrumentator

from app.alert_normalizer import AlertNormalizer
from app.anomaly_analyzer import AnomalyAnalyzer
from app.config import Settings
from app.context import AppCtx, get_conn, get_ctx
from app.db import make_pg_pool
from app.evidence_builder import EvidenceBuilder
from app.incident_correlator import IncidentCorrelator
from app.kubernetes_evidence import KubernetesEvidenceCollector
from app.loki_evidence import LokiEvidenceCollector
from app.models import (
    AlertIngestionResult,
    AlertmanagerWebhook,
    AnomalyEvaluation,
    CollectorRunResult,
    EvidencePackage,
    EvidenceSnapshot,
    EvaluationRequest,
    IncidentCorrelationRequest,
    IncidentCorrelationResult,
    IncidentCandidate,
    StoredAnomalyCandidate,
)
from app.prometheus_collector import PrometheusCollector
from app.rca_contract import RcaAnalysisRequest, RcaAnalysisResponse, build_mock_rca
from app.tempo_evidence import TempoEvidenceCollector
from app.queries import (
    create_incident_evidence_snapshot,
    get_incident,
    get_latest_incident_evidence_snapshot,
    list_anomalies,
    list_anomalies_for_incident_window,
    list_incidents,
    list_nearby_firing_alerts,
    upsert_alerts,
    upsert_incident_evidence_links,
    upsert_incidents,
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
    start_at, end_at = builder.time_window(incident)
    anomalies = await list_anomalies_for_incident_window(
        conn,
        start_at=start_at,
        end_at=end_at,
    )
    kubernetes_evidence = None
    if kubernetes_collector is not None:
        kubernetes_evidence = await kubernetes_collector.collect(
            incident, start_at=start_at, end_at=end_at
        )
    logs = (
        await loki_collector.collect(incident, start_at=start_at, end_at=end_at)
        if loki_collector is not None
        else None
    )
    traces = (
        await tempo_collector.collect(incident, start_at=start_at, end_at=end_at)
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
    await upsert_incident_evidence_links(conn, incident_id, package)
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
    conn=Depends(get_conn),
) -> RcaAnalysisResponse:
    """Generate an RCA draft from the incident's latest Evidence snapshot.

    The selected provider is explicit so the dashboard never mistakes a mock
    draft for a Bedrock investigation result.
    """
    snapshot = await get_latest_incident_evidence_snapshot(conn, incident_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="incident evidence snapshot was not found; build evidence first",
        )
    request = RcaAnalysisRequest(evidence=snapshot.package)
    if ctx.settings.operations_rca_provider == "mock":
        return build_mock_rca(request)

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Bedrock RCA provider is configured but not implemented yet",
    )
