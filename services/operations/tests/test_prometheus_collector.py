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


def test_node_not_ready_catalog_entry_has_no_invented_threshold():
    metric = next(item for item in READY_METRICS if item.metric_id == "node_not_ready")

    assert metric.subject_type == "node"
    assert metric.subject_labels == ("node",)
    assert metric.event is True
    assert 'condition="Ready"' in metric.promql
    assert 'status="false"' in metric.promql
    assert "min_over_time" in metric.promql


def test_node_disk_pressure_catalog_entry():
    metric = next(item for item in READY_METRICS if item.metric_id == "node_disk_pressure")

    assert metric.subject_type == "node"
    assert metric.event is True
    assert 'condition="DiskPressure"' in metric.promql
    assert 'status="true"' in metric.promql


def test_deployment_replicas_unavailable_catalog_entry():
    metric = next(
        item for item in READY_METRICS if item.metric_id == "deployment_replicas_unavailable"
    )

    assert metric.subject_type == "deployment"
    assert metric.subject_labels == ("namespace", "deployment")
    assert metric.event is True
    assert "kube_deployment_status_replicas_unavailable" in metric.promql
    assert "[10m:1m]" in metric.promql


def test_pvc_disk_high_catalog_entry_reuses_es_minio_85_percent_threshold():
    metric = next(item for item in READY_METRICS if item.metric_id == "pvc_disk_high")

    assert metric.subject_type == "pvc"
    assert metric.subject_labels == ("namespace", "persistentvolumeclaim")
    assert metric.event is True
    assert "kubelet_volume_stats_available_bytes" in metric.promql
    assert "kubelet_volume_stats_capacity_bytes" in metric.promql
    # Same number already proven by mealplanning-config's MpESDiskHigh/
    # MpMinIODiskHigh, not a newly invented threshold.
    assert "> bool 85" in metric.promql
    assert "[30m:1m]" in metric.promql


def test_mesh_5xx_rate_catalog_entry_uses_istio_destination_telemetry():
    metric = next(item for item in READY_METRICS if item.metric_id == "mesh_5xx_rate")

    assert metric.subject_type == "istio_service"
    assert metric.subject_labels == ("destination_service_name",)
    assert metric.event is False
    assert metric.p95_request_rate_guard is False
    assert 'reporter="destination"' in metric.promql
    assert 'destination_service_namespace="app"' in metric.promql
    assert 'response_code=~"5.."' in metric.promql
    assert "or on(destination_service_name) (0 *" in metric.promql
    assert "and on(destination_service_name)" in metric.promql


def test_dns_servfail_rate_catalog_entry():
    metric = next(item for item in READY_METRICS if item.metric_id == "dns_servfail_rate")

    assert metric.subject_type == "coredns_instance"
    assert metric.subject_labels == ("namespace", "pod")
    assert metric.event is False
    assert 'namespace="kube-system"' in metric.promql
    assert 'rcode="SERVFAIL"' in metric.promql
    assert "or on(namespace, pod) (0 *" in metric.promql


def test_collector_persists_node_not_ready_as_event():
    metric = next(item for item in READY_METRICS if item.metric_id == "node_not_ready")
    client = FakePrometheusClient(
        instants=[[], [_series({"node": "k8s-worker-b1"}, [1.0])]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.event_candidates == 1
    assert result.stored_candidates == 1
    params = conn.executed[0][1]
    assert params["subject_key"] == "k8s-worker-b1"
    assert params["status"] == "anomaly"


def test_collector_persists_mesh_5xx_as_statistical_candidate():
    metric = next(item for item in READY_METRICS if item.metric_id == "mesh_5xx_rate")
    values = [0.0, 0.0, 0.0] * 10 + [40.0, 55.0, 70.0]
    client = FakePrometheusClient(
        instants=[[]],
        ranges=[[_series({"destination_service_name": "recipe"}, values)]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.evaluated_series == 1
    assert result.stored_candidates == 1
    assert conn.executed[0][1]["subject_key"] == "recipe"


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
