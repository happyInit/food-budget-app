from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

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


def test_all_catalog_promql_queries_have_balanced_parentheses():
    """A stray/missing paren produces a query that's still a plausible-looking
    string (existing per-metric tests here only substring-match fragments of
    it, which is exactly why this slipped through review), but Prometheus
    rejects it outright at query time. Confirmed live (2026-08-17): both
    mesh_5xx_rate and dns_servfail_rate carried one extra ")" right before
    their "and on(...)" clause, so every anomaly-detection poll for those
    two metrics 400'd against Prometheus and never produced data.
    """
    for metric in READY_METRICS:
        depth = 0
        for char in metric.promql:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                assert depth >= 0, (
                    f"{metric.metric_id}: unmatched ')' — promql has more "
                    f"closing than opening parentheses at that point"
                )
        assert depth == 0, (
            f"{metric.metric_id}: unbalanced parentheses ({depth:+d}) in promql"
        )


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


def test_postgres_connection_ratio_catalog_entry():
    pg = next(item for item in READY_METRICS if item.metric_id == "postgres_connection_ratio")

    assert pg.subject_type == "postgres_instance"
    assert pg.subject_labels == ("namespace", "pod")
    assert "cnpg_backends_total" in pg.promql
    # % of max_connections, not a raw connection count — a raw count was
    # confirmed by live measurement to be a flat series (pg-1=2, pg-2=1,
    # 24h stddev=0.0) that would false-positive on any single-connection
    # move.
    assert "cnpg_pg_settings_setting" in pg.promql
    assert 'name="max_connections"' in pg.promql
    assert pg.minimum_current_value == 1.0
    assert pg.minimum_absolute_delta == 1.0


def test_collector_excludes_flat_low_connection_count_noise():
    """Regression guard for the raw-connection-count false positive found in
    review: baseline steady at 2 connections out of 100 must not be flagged
    just because dispersion is ~0."""
    metric = next(
        item for item in READY_METRICS if item.metric_id == "postgres_connection_ratio"
    )
    values = [2.0] * 33  # 2% of 100 max_connections, perfectly flat
    client = FakePrometheusClient(
        instants=[[]],
        ranges=[[_series({"namespace": "data", "pod": "pg-1"}, values)]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.stored_candidates == 0
    assert conn.executed == []


def test_elasticsearch_heap_high_catalog_entry_uses_static_threshold():
    es = next(item for item in READY_METRICS if item.metric_id == "elasticsearch_heap_high")

    assert es.subject_type == "elasticsearch_node"
    assert es.subject_labels == ("namespace", "name")
    assert es.event is True
    assert "elasticsearch_jvm_memory_used_bytes" in es.promql
    assert "elasticsearch_jvm_memory_max_bytes" in es.promql
    assert 'area="heap"' in es.promql
    # Static threshold, not rolling z-score/MAD — review found the real
    # signal is a GC sawtooth (24h: min 23.2%, max 74.6%, stddev 16.3pp)
    # that a rolling baseline can neither reach (z=3 needs ~49pp) nor stay
    # quiet on (change_rate fires on ordinary post-GC swings).
    assert "> 85" in es.promql


def test_collector_persists_high_heap_as_event():
    metric = next(item for item in READY_METRICS if item.metric_id == "elasticsearch_heap_high")
    client = FakePrometheusClient(
        instants=[[], [_series(
            {"namespace": "data", "name": "es-es-b-1"},
            [91.4],
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
    assert params["subject_key"] == "data/es-es-b-1"
    assert params["status"] == "anomaly"
    assert params["event_count"] == 91.4


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


def test_backup_stale_catalog_reuses_mpbackup_thresholds():
    metric = next(item for item in READY_METRICS if item.metric_id == "backup_stale")

    assert metric.subject_type == "backup_track"
    assert metric.subject_labels == ("track",)
    assert metric.event is True
    # Same five tracks and thresholds as the live mp-backup PrometheusRule
    # (mealplanning-config monitoring/base/rules-backup.yaml) — not
    # reinvented here.
    assert "> 2700" in metric.promql
    assert "> 108000" in metric.promql
    assert "> 777600" in metric.promql
    assert "> 3024000" in metric.promql
    assert 'track="pg_wal"' in metric.promql
    assert 'track="secrets"' in metric.promql
    assert 'track="source"' in metric.promql


def test_collector_persists_stale_backup_track_as_event():
    metric = next(item for item in READY_METRICS if item.metric_id == "backup_stale")
    client = FakePrometheusClient(
        instants=[[], [_series({"track": "pg_wal"}, [4200.0])]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.event_candidates == 1
    assert result.stored_candidates == 1
    params = conn.executed[0][1]
    assert params["subject_key"] == "pg_wal"
    assert params["status"] == "anomaly"
    assert params["event_count"] == 4200.0


def test_backup_probe_missing_catalog_entry_has_no_subject_labels():
    metric = next(item for item in READY_METRICS if item.metric_id == "backup_probe_missing")

    assert metric.subject_type == "backup_probe"
    assert metric.subject_labels == ()
    assert metric.event is True
    assert metric.promql == "absent(mp_backup_check_timestamp_seconds)"


def test_collector_persists_missing_backup_probe_as_event():
    """absent() emits a labelless series only when the metric doesn't exist
    at all — must still produce a valid (empty-string) subject_key rather
    than being dropped as unidentifiable."""
    metric = next(item for item in READY_METRICS if item.metric_id == "backup_probe_missing")
    client = FakePrometheusClient(
        instants=[[], [_series({}, [1.0])]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.event_candidates == 1
    assert result.stored_candidates == 1
    params = conn.executed[0][1]
    assert params["subject_key"] == ""
    assert params["status"] == "anomaly"


def test_backup_probe_failed_and_image_never_archived_catalog_entries():
    probe_failed = next(
        item for item in READY_METRICS if item.metric_id == "backup_probe_failed"
    )
    image_never_archived = next(
        item for item in READY_METRICS if item.metric_id == "backup_image_never_archived"
    )

    assert probe_failed.subject_type == "backup_track"
    assert probe_failed.subject_labels == ("track",)
    assert probe_failed.event is True
    # "== bool 0" so a real failure (value 0) still yields a positive
    # event value (1) instead of being skipped by the event path's
    # value>0-means-anomaly check.
    assert probe_failed.promql == "mp_backup_check_success == bool 0"

    assert image_never_archived.subject_type == "backup_track"
    assert image_never_archived.event is True
    assert image_never_archived.promql == (
        'mp_backup_object_count{track="image"} == bool 0'
    )


def test_collector_persists_failed_backup_probe_as_event():
    metric = next(
        item for item in READY_METRICS if item.metric_id == "backup_probe_failed"
    )
    client = FakePrometheusClient(
        instants=[[], [_series({"track": "pg_wal"}, [1.0])]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.event_candidates == 1
    assert result.stored_candidates == 1
    assert conn.executed[0][1]["subject_key"] == "pg_wal"


def test_backup_pg_onsite_dump_stale_catalog_entry():
    metric = next(
        item for item in READY_METRICS if item.metric_id == "backup_pg_onsite_dump_stale"
    )
    assert metric.subject_type == "cronjob"
    assert metric.subject_labels == ("namespace", "cronjob")
    assert metric.event is True
    assert "kube_cronjob_status_last_successful_time" in metric.promql
    assert 'cronjob="mp-pg-onsite-dump"' in metric.promql
    assert "> 108000" in metric.promql


def test_app_symptom_catalog_entries_use_absolute_counts_not_ratios():
    auth = next(item for item in READY_METRICS if item.metric_id == "auth_path_failing")
    mealplan = next(
        item for item in READY_METRICS if item.metric_id == "mealplan_recommend_failing"
    )
    accumulating = next(
        item for item in READY_METRICS if item.metric_id == "app_errors_accumulating"
    )

    assert auth.subject_labels == ()
    assert auth.event is True
    assert "handler=~\"/api/auth/(login|signup|refresh|google|kakao)\"" in auth.promql
    assert ">= bool 5" in auth.promql
    assert "[15m:1m]" in auth.promql
    # 4xx deliberately excluded — account's baseline 401 rate is 42.8%
    # (expired tokens/anonymous access mixed in normally).
    assert "status=~\"5..\"" in auth.promql
    assert "4.." not in auth.promql

    assert mealplan.subject_labels == ()
    assert "handler=\"/api/mealplan/recommend\"" in mealplan.promql
    assert ">= bool 3" in mealplan.promql

    assert accumulating.subject_type == "service"
    assert accumulating.subject_labels == ("service",)
    assert ">= bool 10" in accumulating.promql
    assert "[30m:1m]" in accumulating.promql


def test_collector_persists_auth_path_failing_as_event():
    metric = next(item for item in READY_METRICS if item.metric_id == "auth_path_failing")
    client = FakePrometheusClient(
        instants=[[], [_series({}, [1.0])]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.event_candidates == 1
    assert result.stored_candidates == 1
    assert conn.executed[0][1]["subject_key"] == ""


def test_memory_near_limit_catalog_entries_use_separate_thresholds():
    container = next(
        item for item in READY_METRICS if item.metric_id == "container_memory_near_limit"
    )
    es = next(
        item for item in READY_METRICS if item.metric_id == "elasticsearch_memory_near_limit"
    )

    assert container.subject_labels == ("namespace", "pod", "container")
    assert container.event is True
    assert "> 0.85" in container.promql
    # Excludes the ES container — it gets its own, higher threshold below
    # since ~87% resident is normal for it.
    assert 'container!="elasticsearch"' in container.promql

    assert es.subject_labels == ("namespace", "pod", "container")
    assert 'container="elasticsearch"' in es.promql
    assert "> 0.90" in es.promql


def test_collector_persists_container_memory_near_limit_as_event():
    metric = next(
        item for item in READY_METRICS if item.metric_id == "container_memory_near_limit"
    )
    client = FakePrometheusClient(
        instants=[[], [_series(
            {"namespace": "app", "pod": "mp-recipe-abc", "container": "recipe"},
            [0.91],
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
    assert params["subject_key"] == "app/mp-recipe-abc/recipe"
    assert params["event_count"] == 0.91




def test_rollout_catalog_entries_avoid_the_namespace_label_trap():
    aborted = next(item for item in READY_METRICS if item.metric_id == "rollout_aborted")
    controller_down = next(
        item for item in READY_METRICS if item.metric_id == "rollouts_controller_down"
    )
    error = next(item for item in READY_METRICS if item.metric_id == "rollout_error")
    stuck = next(item for item in READY_METRICS if item.metric_id == "rollout_stuck")

    # rollout_phase's own `namespace` label is always "argo-rollouts" (the
    # ServiceMonitor scrape target overwrites it) — must identify by `name`,
    # never filter on namespace.
    assert aborted.subject_labels == ("name",)
    assert "namespace=" not in aborted.promql
    assert 'phase="Abort"' in aborted.promql
    assert "[2m]" in aborted.promql

    assert controller_down.subject_labels == ()
    assert "rollouts-argo-rollouts-metrics" in controller_down.promql

    assert error.subject_labels == ("name", "phase")
    assert 'phase=~"Error|Timeout"' in error.promql
    assert "[5m]" in error.promql

    assert stuck.subject_labels == ("name", "phase")
    assert 'phase=~"Paused|Progressing"' in stuck.promql
    assert "[30m]" in stuck.promql


def test_collector_persists_aborted_rollout_as_event():
    metric = next(item for item in READY_METRICS if item.metric_id == "rollout_aborted")
    client = FakePrometheusClient(
        instants=[[], [_series({"name": "mp-account"}, [1.0])]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.event_candidates == 1
    assert result.stored_candidates == 1
    params = conn.executed[0][1]
    assert params["subject_key"] == "mp-account"
    assert params["status"] == "anomaly"


def test_collector_persists_stuck_rollout_as_event():
    metric = next(item for item in READY_METRICS if item.metric_id == "rollout_stuck")
    client = FakePrometheusClient(
        instants=[[], [_series({"name": "mp-recipe", "phase": "Progressing"}, [1.0])]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.event_candidates == 1
    assert result.stored_candidates == 1
    assert conn.executed[0][1]["subject_key"] == "mp-recipe/Progressing"



def test_elasticsearch_cluster_health_catalog_entries():
    unavailable = next(
        item for item in READY_METRICS if item.metric_id == "elasticsearch_metrics_unavailable"
    )
    yellow = next(item for item in READY_METRICS if item.metric_id == "elasticsearch_cluster_yellow")
    red = next(item for item in READY_METRICS if item.metric_id == "elasticsearch_cluster_red")
    disk = next(item for item in READY_METRICS if item.metric_id == "elasticsearch_disk_high")

    assert unavailable.subject_labels == ()
    assert "mp-elasticsearch-exporter" in unavailable.promql

    assert yellow.subject_labels == ()
    assert yellow.event is True
    assert 'color="yellow"' in yellow.promql
    assert "[30m]" in yellow.promql

    assert red.subject_labels == ()
    assert 'color="red"' in red.promql
    assert "[5m]" in red.promql

    assert disk.subject_type == "elasticsearch_volume"
    assert disk.subject_labels == ("namespace", "persistentvolumeclaim")
    assert "> 0.85" in disk.promql


def test_collector_persists_es_cluster_red_as_event():
    metric = next(item for item in READY_METRICS if item.metric_id == "elasticsearch_cluster_red")
    client = FakePrometheusClient(
        instants=[[], [_series({}, [1.0])]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.event_candidates == 1
    assert result.stored_candidates == 1
    assert conn.executed[0][1]["subject_key"] == ""



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


def test_poller_job_failed_catalog_entry():
    metric = next(item for item in READY_METRICS if item.metric_id == "poller_job_failed")

    assert metric.subject_type == "job"
    assert metric.subject_labels == ("namespace", "job_name")
    assert metric.event is True
    assert "kube_job_status_failed" in metric.promql
    assert 'namespace="pipeline"' in metric.promql
    # Not scoped to Kurly — an outright job failure isn't a Kurly-specific
    # failure mode the way silent truncation is.
    assert "mp-poller-kurly" not in metric.promql


def test_collector_persists_failed_job_as_event():
    metric = next(item for item in READY_METRICS if item.metric_id == "poller_job_failed")
    client = FakePrometheusClient(
        instants=[[], [_series(
            {"namespace": "pipeline", "job_name": "mp-poller-kurly-29773110"},
            [1.0],
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
    assert params["subject_key"] == "pipeline/mp-poller-kurly-29773110"
    assert params["status"] == "anomaly"
    assert params["event_count"] == 1.0


def test_collector_excludes_low_absolute_cpu_noise_even_when_statistically_anomalous():
    metric = CatalogMetric(
        metric_id="pod_cpu_usage",
        subject_type="pod_container",
        subject_labels=("namespace", "pod", "container"),
        promql="cpu_query",
        minimum_current_value=0.05,
        minimum_absolute_delta=0.025,
    )
    client = FakePrometheusClient(
        instants=[[]],
        ranges=[[_series({"namespace": "data", "pod": "pg-2", "container": "postgres"}, [0.007, 0.008, 0.0075] * 10 + [0.009, 0.01, 0.012])]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.stored_candidates == 0
    assert conn.executed == []


def test_collector_does_not_filter_request_rate_drop_to_zero():
    """direction="both" on service_request_rate exists specifically to catch
    traffic falling off a cliff. Checking only the current value's magnitude
    against minimum_current_value would filter out exactly that: current=0
    always looks negligible on its own, even when the baseline was 5 req/s."""
    metric = next(item for item in READY_METRICS if item.metric_id == "service_request_rate")
    baseline = [5.0, 5.2, 4.8] * 10
    values = baseline + [0.0, 0.0, 0.0]
    client = FakePrometheusClient(
        instants=[[]],
        ranges=[[_series({"service": "recipe"}, values)]],
    )
    conn = FakeConn()
    collector = PrometheusCollector(
        settings=Settings(), analyzer=AnomalyAnalyzer(), client=client, catalog=(metric,)
    )

    result = asyncio.run(collector.collect_once(conn))

    assert result.stored_candidates == 1
    assert conn.executed[0][1]["status"] == "anomaly"


def test_event_metric_with_significance_floor_raises_at_definition():
    with pytest.raises(ValueError, match="significance floors are not applied"):
        CatalogMetric(
            metric_id="broken",
            subject_type="pod_container",
            subject_labels=("namespace", "pod", "container"),
            promql="broken_query",
            event=True,
            minimum_current_value=1.0,
        )


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
