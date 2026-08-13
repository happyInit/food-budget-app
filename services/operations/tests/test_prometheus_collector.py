from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.anomaly_analyzer import AnomalyAnalyzer
from app.config import Settings
from app.metric_catalog import READY_METRICS, CatalogMetric
from app.models import TimeSeriesPoint
from app.prometheus_client import PrometheusSeries
from app.prometheus_collector import PrometheusCollector
from tests.fakes import FakeConn


class FakePrometheusClient:
    def __init__(self, *, ranges=(), instants=()) -> None:
        self.ranges = list(ranges)
        self.instants = list(instants)
        self.range_queries: list[str] = []
        self.instant_queries: list[str] = []

    async def query_range(self, promql, **kwargs):
        self.range_queries.append(promql)
        return self.ranges.pop(0)

    async def query(self, promql, **kwargs):
        self.instant_queries.append(promql)
        return self.instants.pop(0)


def _series(labels: dict[str, str], values: list[float]) -> PrometheusSeries:
    start = datetime(2026, 7, 30, 0, 0, tzinfo=timezone.utc)
    return PrometheusSeries(
        labels=labels,
        points=[
            TimeSeriesPoint(
                timestamp=start + timedelta(minutes=index), value=value
            )
            for index, value in enumerate(values)
        ],
    )


def test_collector_skips_idle_p95_series_before_analyzer():
    metric = next(item for item in READY_METRICS if item.metric_id == "service_p95_latency")
    client = FakePrometheusClient(
        instants=[[_series({"service": "recipe"}, [0.0])]],
        ranges=[[_series({"service": "recipe"}, [100.0] * 40)]],
    )
    collector = PrometheusCollector(
        settings=Settings(operations_min_request_rate=0.1),
        analyzer=AnomalyAnalyzer(),
        client=client,
        catalog=(metric,),
    )

    result = asyncio.run(collector.collect_once(FakeConn()))

    assert result.collected_series == 1
    assert result.skipped_series == 1
    assert result.evaluated_series == 0
    assert result.stored_candidates == 0


def test_service_5xx_rate_catalog_keeps_zero_baseline_and_excludes_canaries():
    metric = next(item for item in READY_METRICS if item.metric_id == "service_5xx_rate")

    assert metric.subject_type == "service"
    assert metric.subject_labels == ("service",)
    assert metric.p95_request_rate_guard is True
    assert "http_requests_total" in metric.promql
    assert 'status=~"5.."' in metric.promql
    assert 'service!~".*-canary"' in metric.promql
    assert "or on(service) (0 *" in metric.promql
    assert "and on(service)" in metric.promql


def test_collector_persists_statistical_anomaly_candidate():
    metric = CatalogMetric(
        metric_id="test_latency",
        subject_type="service",
        subject_labels=("service",),
        promql="test_latency",
    )
    values = [98.0, 100.0, 102.0] * 10 + [130.0, 170.0, 220.0]
    client = FakePrometheusClient(
        instants=[[]],
        ranges=[[_series({"service": "recipe"}, values)]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(),
        analyzer=AnomalyAnalyzer(),
        client=client,
        catalog=(metric,),
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.evaluated_series == 1
    assert result.stored_candidates == 1
    assert "insert into operations.anomalies" in conn.executed[0][0]
    assert conn.executed[0][1]["status"] == "anomaly"
    assert conn.executed[0][1]["subject_key"] == "recipe"


def test_poller_stale_catalog_reuses_mppollerstale_thresholds():
    metric = next(item for item in READY_METRICS if item.metric_id == "poller_stale")

    assert metric.subject_type == "cronjob"
    assert metric.subject_labels == ("namespace", "cronjob")
    assert metric.event is True
    assert "kube_cronjob_status_last_successful_time" in metric.promql
    # Same three cadence groups and thresholds as the live MpPollerStale
    # PrometheusRule (mealplanning-config pipelines/base/monitoring.yaml) —
    # not reinvented here.
    assert "> 10800" in metric.promql
    assert "> 108000" in metric.promql
    assert "> 432000" in metric.promql
    assert "mp-poller-kurly" in metric.promql


def test_collector_persists_stale_poller_as_event():
    metric = next(item for item in READY_METRICS if item.metric_id == "poller_stale")
    client = FakePrometheusClient(
        instants=[[], [_series(
            {"namespace": "pipeline", "cronjob": "mp-poller-kurly"},
            [172800.0],
        )]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.event_candidates == 1
    assert result.stored_candidates == 1
    params = conn.executed[0][1]
    assert params["subject_key"] == "pipeline/mp-poller-kurly"
    assert params["status"] == "anomaly"
    assert params["event_count"] == 172800.0


def test_poller_kurly_truncated_catalog_reuses_mpkurlycrawltruncated_threshold():
    metric = next(item for item in READY_METRICS if item.metric_id == "poller_kurly_truncated")

    assert metric.subject_type == "job"
    assert metric.subject_labels == ("namespace", "job_name")
    assert metric.event is True
    assert "kube_job_status_completion_time" in metric.promql
    assert "kube_job_status_start_time" in metric.promql
    # Same 180s threshold as the live MpKurlyCrawlTruncated PrometheusRule —
    # not reinvented here.
    assert "< 180" in metric.promql
    assert "mp-poller-kurly-[0-9]+" in metric.promql


def test_collector_persists_truncated_kurly_run_as_event():
    metric = next(
        item for item in READY_METRICS if item.metric_id == "poller_kurly_truncated"
    )
    client = FakePrometheusClient(
        instants=[[], [_series(
            {"namespace": "pipeline", "job_name": "mp-poller-kurly-29770230"},
            [26.0],
        )]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.event_candidates == 1
    assert result.stored_candidates == 1
    params = conn.executed[0][1]
    assert params["subject_key"] == "pipeline/mp-poller-kurly-29770230"
    assert params["status"] == "anomaly"
    assert params["event_count"] == 26.0


def test_collector_persists_restart_as_event_without_statistical_score():
    metric = CatalogMetric(
        metric_id="pod_restart_increase",
        subject_type="pod_container",
        subject_labels=("namespace", "pod", "container"),
        promql="restart_query",
        event=True,
    )
    client = FakePrometheusClient(
        instants=[[], [_series(
            {"namespace": "app", "pod": "mp-recipe-abc", "container": "recipe"},
            [2.0],
        )]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(),
        analyzer=AnomalyAnalyzer(),
        client=client,
        catalog=(metric,),
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.event_candidates == 1
    assert result.stored_candidates == 1
    params = conn.executed[0][1]
    assert params["event_count"] == 2.0
    assert params["z_score"] is None
