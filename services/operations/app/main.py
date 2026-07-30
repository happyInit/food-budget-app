from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.alert_normalizer import AlertNormalizer
from app.anomaly_analyzer import AnomalyAnalyzer
from app.config import Settings
from app.context import AppCtx, get_conn
from app.db import make_pg_pool
from app.incident_correlator import IncidentCorrelator
from app.models import (
    AlertIngestionResult,
    AlertmanagerWebhook,
    AnomalyEvaluation,
    EvaluationRequest,
    IncidentCorrelationRequest,
    IncidentCorrelationResult,
)
from app.queries import list_nearby_firing_alerts, upsert_alerts, upsert_incidents


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    pool = make_pg_pool(settings) if settings.operations_database_enabled else None
    if pool is not None:
        await pool.open()
    app.state.ctx = AppCtx(pool=pool, settings=settings)
    try:
        yield
    finally:
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
