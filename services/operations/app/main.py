from __future__ import annotations

from fastapi import Depends, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.alert_normalizer import AlertNormalizer
from app.anomaly_analyzer import AnomalyAnalyzer
from app.incident_correlator import IncidentCorrelator
from app.models import (
    AlertIngestionResult,
    AlertmanagerWebhook,
    AnomalyEvaluation,
    EvaluationRequest,
    IncidentCorrelationRequest,
    IncidentCorrelationResult,
)


app = FastAPI(title="Operations Service", version="0.1.0")
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
) -> AlertIngestionResult:
    return normalizer.normalize(payload)


@app.post(
    "/internal/incidents/correlate",
    response_model=IncidentCorrelationResult,
)
async def correlate_incidents(
    request: IncidentCorrelationRequest,
    correlator: IncidentCorrelator = Depends(get_incident_correlator),
) -> IncidentCorrelationResult:
    return correlator.correlate(request)
