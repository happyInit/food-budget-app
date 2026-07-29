from __future__ import annotations

from fastapi import Depends, FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from app.anomaly_analyzer import AnomalyAnalyzer
from app.models import AnomalyEvaluation, EvaluationRequest


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


def get_analyzer() -> AnomalyAnalyzer:
    return _analyzer


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
