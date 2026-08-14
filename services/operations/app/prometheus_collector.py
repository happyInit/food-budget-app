from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.anomaly_analyzer import AnomalyAnalyzer
from app.config import Settings
from app.metric_catalog import P95_REQUEST_RATE_PROMQL, READY_METRICS, CatalogMetric
from app.models import AnomalyEvaluation, EvaluationRequest, EvaluationResult
from app.prometheus_client import PrometheusClient, PrometheusSeries
from app.queries import upsert_anomaly_candidates

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnomalyCandidate:
    metric_id: str
    subject_type: str
    subject_key: str
    labels: dict[str, str]
    evaluated_at: datetime
    status: str
    current_value: float
    evaluation: EvaluationResult | None = None
    event_count: float | None = None


@dataclass(frozen=True)
class CollectorRunResult:
    collected_series: int = 0
    evaluated_series: int = 0
    skipped_series: int = 0
    stored_candidates: int = 0
    event_candidates: int = 0
    errors: int = 0


class PrometheusCollector:
    """Reads Ready catalog metrics and persists only meaningful anomaly signals."""

    def __init__(
        self,
        *,
        settings: Settings,
        analyzer: AnomalyAnalyzer,
        client: PrometheusClient | None = None,
        catalog: tuple[CatalogMetric, ...] = READY_METRICS,
    ) -> None:
        self._settings = settings
        self._analyzer = analyzer
        self._client = client or PrometheusClient(settings.operations_prometheus_url)
        self._catalog = catalog

    async def collect_once(self, conn, now: datetime | None = None) -> CollectorRunResult:
        now = now or datetime.now(timezone.utc)
        start = now - timedelta(minutes=self._settings.operations_collector_lookback_minutes)
        request_rate_by_service = await self._request_rates(now)
        candidates: list[AnomalyCandidate] = []
        collected = evaluated = skipped = errors = event_count = 0

        for metric in self._catalog:
            try:
                if metric.event:
                    series = await self._client.query(metric.promql, at=now)
                    collected += len(series)
                    event_candidates = self._event_candidates(metric, series)
                    event_count += len(event_candidates)
                    candidates.extend(event_candidates)
                    continue

                series = await self._client.query_range(
                    metric.promql,
                    start=start,
                    end=now,
                    step_seconds=self._settings.operations_collector_step_seconds,
                )
                collected += len(series)
                for item in series:
                    if metric.p95_request_rate_guard and not self._has_minimum_request_rate(
                        item, request_rate_by_service
                    ):
                        skipped += 1
                        continue
                    candidate = self._evaluate_series(metric, item)
                    if candidate is None:
                        skipped += 1
                        continue
                    evaluated += 1
                    if candidate.status in {"candidate", "anomaly"}:
                        candidates.append(candidate)
            except Exception:
                errors += 1
                logger.exception("Prometheus collection failed", extra={"metric_id": metric.metric_id})

        if candidates:
            await upsert_anomaly_candidates(conn, candidates)

        return CollectorRunResult(
            collected_series=collected,
            evaluated_series=evaluated,
            skipped_series=skipped,
            stored_candidates=len(candidates),
            event_candidates=event_count,
            errors=errors,
        )

    async def run_forever(self, conn_provider) -> None:
        while True:
            try:
                async with conn_provider() as conn:
                    await self.collect_once(conn)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduled Prometheus collection failed")
            await asyncio.sleep(self._settings.operations_collector_interval_seconds)

    async def _request_rates(self, now: datetime) -> dict[str, float]:
        series = await self._client.query(P95_REQUEST_RATE_PROMQL, at=now)
        return {
            item.labels["service"]: item.points[-1].value
            for item in series
            if item.labels.get("service") and item.points
        }

    def _has_minimum_request_rate(
        self, series: PrometheusSeries, request_rate_by_service: dict[str, float]
    ) -> bool:
        service = series.labels.get("service")
        return bool(service) and request_rate_by_service.get(service, 0.0) >= self._settings.operations_min_request_rate

    def _evaluate_series(
        self, metric: CatalogMetric, series: PrometheusSeries
    ) -> AnomalyCandidate | None:
        subject_key = self._subject_key(metric, series.labels)
        if subject_key is None or len(series.points) < 2:
            return None
        result: AnomalyEvaluation = self._analyzer.evaluate(
            EvaluationRequest(
                service=subject_key,
                metric=metric.metric_id,
                points=series.points,
                config=metric.analyzer_config or self._settings.analyzer_config,
            )
        )
        if not isinstance(result, EvaluationResult):
            return None
        if not self._is_actionable_metric_value(metric, result):
            return None
        return AnomalyCandidate(
            metric_id=metric.metric_id,
            subject_type=metric.subject_type,
            subject_key=subject_key,
            labels=series.labels,
            evaluated_at=result.evaluated_at,
            status=result.status,
            current_value=result.current_value,
            evaluation=result,
        )

    @staticmethod
    def _is_actionable_metric_value(
        metric: CatalogMetric, result: EvaluationResult
    ) -> bool:
        """Reject statistical noise before it reaches persistence/RCA.

        This gate is deliberately metric-specific and uses units from the
        catalog (cores, bytes, percentages, requests/sec), not display values.
        """
        baseline = result.baseline.mean
        if metric.require_nonzero_baseline and abs(baseline) <= 1e-12:
            return False
        if (
            metric.minimum_current_value is not None
            # A drop to (near) zero is itself the signal for direction="both"
            # metrics like service_request_rate — checking only the current
            # value would filter out exactly the "traffic fell off a cliff"
            # case this metric exists to catch. Pass if either side of the
            # move was large enough to matter.
            and max(abs(result.current_value), abs(baseline))
            < metric.minimum_current_value
        ):
            return False
        if (
            metric.minimum_absolute_delta is not None
            and abs(result.current_value - baseline) < metric.minimum_absolute_delta
        ):
            return False
        return True

    def _event_candidates(
        self, metric: CatalogMetric, series: list[PrometheusSeries]
    ) -> list[AnomalyCandidate]:
        candidates: list[AnomalyCandidate] = []
        for item in series:
            if not item.points or item.points[-1].value <= 0:
                continue
            subject_key = self._subject_key(metric, item.labels)
            if subject_key is None:
                continue
            candidates.append(
                AnomalyCandidate(
                    metric_id=metric.metric_id,
                    subject_type=metric.subject_type,
                    subject_key=subject_key,
                    labels=item.labels,
                    evaluated_at=item.points[-1].timestamp,
                    status="anomaly",
                    current_value=item.points[-1].value,
                    event_count=item.points[-1].value,
                )
            )
        return candidates

    @staticmethod
    def _subject_key(metric: CatalogMetric, labels: dict[str, str]) -> str | None:
        values = [labels.get(label) for label in metric.subject_labels]
        if any(value is None or value == "" for value in values):
            return None
        return "/".join(values)
