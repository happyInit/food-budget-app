from __future__ import annotations

from dataclasses import dataclass

from app.models import AnalyzerConfig


@dataclass(frozen=True)
class CatalogMetric:
    """A Prometheus query contract for one Operations detection target."""

    metric_id: str
    subject_type: str
    subject_labels: tuple[str, ...]
    promql: str
    analyzer_config: AnalyzerConfig | None = None
    event: bool = False
    p95_request_rate_guard: bool = False
    # Statistical significance alone is not an investigation priority.  These
    # floors prevent a nearly flat series from becoming an actionable signal.
    minimum_current_value: float | None = None
    minimum_absolute_delta: float | None = None
    require_nonzero_baseline: bool = False

    def __post_init__(self) -> None:
        # PrometheusCollector._is_actionable_metric_value() only runs in the
        # statistical path (_evaluate_series) — event candidates skip it
        # entirely. A floor set here on an event=True metric would silently
        # do nothing rather than filter anything, so fail loudly instead.
        if self.event and (
            self.minimum_current_value is not None
            or self.minimum_absolute_delta is not None
            or self.require_nonzero_baseline
        ):
            raise ValueError(
                f"{self.metric_id}: significance floors are not applied to "
                "event metrics — remove them, or wire the gate into "
                "_event_candidates first"
            )


APP_NAMESPACES = 'namespace=~"app|data|pipeline"'


READY_METRICS: tuple[CatalogMetric, ...] = (
    CatalogMetric(
        metric_id="service_p95_latency",
        subject_type="service",
        subject_labels=("service",),
        promql=(
            "histogram_quantile(0.95, "
            "sum by(service, le) "
            "(rate(http_request_duration_highr_seconds_bucket{namespace=\"app\"}[5m])))"
        ),
        p95_request_rate_guard=True,
    ),
    CatalogMetric(
        metric_id="service_request_rate",
        subject_type="service",
        subject_labels=("service",),
        promql=(
            "sum by(service) "
            "(rate(http_request_duration_highr_seconds_count{namespace=\"app\"}[5m]))"
        ),
        analyzer_config=AnalyzerConfig(direction="both"),
        minimum_current_value=0.1,
        require_nonzero_baseline=True,
    ),
    CatalogMetric(
        metric_id="service_5xx_rate",
        subject_type="service",
        subject_labels=("service",),
        promql=(
            "(100 * ("
            "(sum by(service) (rate(http_requests_total{namespace=\"app\", "
            "service!~\".*-canary\", status=~\"5..\"}[5m])) "
            "or on(service) (0 * sum by(service) "
            "(rate(http_requests_total{namespace=\"app\", "
            "service!~\".*-canary\"}[5m])))) "
            "/ sum by(service) (rate(http_requests_total{namespace=\"app\", "
            "service!~\".*-canary\"}[5m]))"
            ")) and on(service) (sum by(service) "
            "(rate(http_requests_total{namespace=\"app\", "
            "service!~\".*-canary\"}[5m])) > 0)"
        ),
        minimum_current_value=0.1,
        minimum_absolute_delta=0.1,
        # Low-traffic services can otherwise turn one expected transient error
        # into a statistically large ratio. Reuse the existing request-rate
        # guard; it does not alter how any application handles requests.
        p95_request_rate_guard=True,
    ),
    CatalogMetric(
        metric_id="pod_cpu_usage",
        subject_type="pod_container",
        subject_labels=("namespace", "pod", "container"),
        promql=(
            "sum by(namespace, pod, container) "
            "(rate(container_cpu_usage_seconds_total{"
            f"{APP_NAMESPACES}, container!=\"\", container!=\"POD\", "
            "container!=\"istio-proxy\", image!=\"\"}[5m]))"
        ),
        minimum_current_value=0.05,
        minimum_absolute_delta=0.025,
    ),
    # 128MiB/64MiB is an absolute floor, not a relative one — a pod whose
    # baseline sits well under it (e.g. the 75MB mp-recipe case this filter
    # was built from) stays unmonitored for statistical drift until it grows
    # past the floor, even for a change that would be large relative to its
    # own size. Traded deliberately for noise reduction; pod_oom_killed
    # (event=True, below) still catches the case where it actually dies.
    CatalogMetric(
        metric_id="pod_memory_working_set",
        subject_type="pod_container",
        subject_labels=("namespace", "pod", "container"),
        promql=(
            "sum by(namespace, pod, container) "
            "(container_memory_working_set_bytes{"
            f"{APP_NAMESPACES}, container!=\"\", container!=\"POD\", "
            "container!=\"istio-proxy\", image!=\"\"})"
        ),
        minimum_current_value=128 * 1024 * 1024,
        minimum_absolute_delta=64 * 1024 * 1024,
    ),
    CatalogMetric(
        metric_id="kafka_consumer_lag",
        subject_type="kafka_consumer",
        subject_labels=("consumergroup", "topic"),
        promql="sum by(consumergroup, topic) (kafka_consumergroup_lag)",
    ),
    CatalogMetric(
        metric_id="redis_memory_ratio",
        subject_type="redis_instance",
        subject_labels=("instance",),
        promql=(
            "100 * redis_memory_used_bytes / redis_memory_max_bytes"
        ),
        minimum_current_value=1.0,
        minimum_absolute_delta=1.0,
        require_nonzero_baseline=True,
    ),
    CatalogMetric(
        metric_id="pod_restart_increase",
        subject_type="pod_container",
        subject_labels=("namespace", "pod", "container"),
        promql=(
            "sum by(namespace, pod, container) "
            "(increase(kube_pod_container_status_restarts_total{"
            f"{APP_NAMESPACES}" "}[5m]))"
        ),
        event=True,
    ),
    CatalogMetric(
        metric_id="pod_oom_killed",
        subject_type="pod_container",
        subject_labels=("namespace", "pod", "container"),
        promql=(
            "sum by(namespace, pod, container) "
            "(changes(kube_pod_container_status_last_terminated_reason{"
            f"{APP_NAMESPACES}, reason=\"OOMKilled\"" "}[5m]))"
        ),
        event=True,
    ),
    # PostgreSQL and Elasticsearch expose their own Prometheus metrics
    # already (CNPG's built-in exporter, a separate elasticsearch_exporter) —
    # no new instrumentation, just querying data that was already there.
    #
    # Raw active-connection count was rejected in review: 24h measurement
    # showed pg-1=2/pg-2=1 with stddev=0.0 — a flat series where even 1->2
    # is a 100% relative move, well past the zero-dispersion path's
    # change_rate_threshold gate, so it would false-positive on the very
    # first batch job. state="active" alone also can't see exhaustion risk
    # (idle-but-held connections still count against the pool). Use % of
    # max_connections instead — matches how this is already read
    # operationally (CLAUDE.md P3 note: "PG 커넥션 12/100"), confirmed against
    # live data (cnpg_pg_settings_setting{name="max_connections"}=100,
    # pg-1 currently at 12%). Floor reuses redis_memory_ratio's values (same
    # percentage-point scale, no new number invented).
    CatalogMetric(
        metric_id="postgres_connection_ratio",
        subject_type="postgres_instance",
        subject_labels=("namespace", "pod"),
        promql=(
            "100 * sum by(namespace, pod) (cnpg_backends_total{namespace=\"data\"}) "
            "/ on(namespace, pod) cnpg_pg_settings_setting{"
            "namespace=\"data\", name=\"max_connections\"}"
        ),
        minimum_current_value=1.0,
        minimum_absolute_delta=1.0,
        require_nonzero_baseline=True,
    ),
    # Rolling z-score/MAD was rejected in review: 24h measurement showed a
    # classic GC sawtooth (min 23.2%, max 74.6%, stddev 16.3pp) — z=3 would
    # need ~49pp deviation from the mean, past the observed ceiling, so a
    # genuinely sustained high-heap problem could never reach it; meanwhile
    # change_rate(0.5) fires on ordinary post-GC swings. JVM heap is a bounded
    # oscillating signal a rolling baseline isn't the right tool for — use a
    # static threshold instead, same event=True + threshold-PromQL pattern as
    # poller_stale above. 85% is the common industry convention for "sustained
    # high JVM heap" cited in review, not validated against this cluster's own
    # load yet — treat as a starting point pending real tuning, same caveat as
    # operations_min_request_rate in config.py.
    CatalogMetric(
        metric_id="elasticsearch_heap_high",
        subject_type="elasticsearch_node",
        subject_labels=("namespace", "name"),
        promql=(
            "100 * elasticsearch_jvm_memory_used_bytes{namespace=\"data\", area=\"heap\"} "
            "/ elasticsearch_jvm_memory_max_bytes{namespace=\"data\", area=\"heap\"} > 85"
        ),
        event=True,
    ),
)

P95_REQUEST_RATE_PROMQL = (
    "sum by(service) "
    "(rate(http_request_duration_highr_seconds_count{namespace=\"app\"}[5m]))"
)
