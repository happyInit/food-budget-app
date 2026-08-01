from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from prometheus_fastapi_instrumentator import Instrumentator

from app.alert_normalizer import AlertNormalizer
from app.anomaly_analyzer import AnomalyAnalyzer
from app.config import Settings
from app.context import AppCtx, get_conn, get_ctx
from app.db import make_pg_pool
from app.evidence_builder import EvidenceBuilder
from app.incident_correlator import IncidentCorrelator
from app.kubernetes_evidence import KubernetesEvidenceCollector
from app.models import (
    AlertIngestionResult,
    AlertmanagerWebhook,
    AnomalyEvaluation,
    CollectorRunResult,
    EvidencePackage,
    EvaluationRequest,
    IncidentCorrelationRequest,
    IncidentCorrelationResult,
)
from app.prometheus_collector import PrometheusCollector
from app.queries import (
    get_incident,
    list_anomalies_for_incident_window,
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
    package = builder.build(
        incident,
        anomalies,
        kubernetes_events=(kubernetes_evidence.events if kubernetes_evidence else None),
        deployments=(kubernetes_evidence.deployments if kubernetes_evidence else None),
    )
    await upsert_incident_evidence_links(conn, incident_id, package)
    return package
