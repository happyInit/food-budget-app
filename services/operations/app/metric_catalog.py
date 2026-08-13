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
    ),
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
    # Staleness thresholds are not new — reused verbatim from the already-live
    # MpPollerStale PrometheusRule (mealplanning-config
    # pipelines/base/monitoring.yaml), grouped by each poller's real run
    # cadence. kube_cronjob_status_last_successful_time comes from
    # kube-state-metrics; no application instrumentation needed.
    #
    # KNOWN GAP (inherited from the source rule, not introduced here — noted
    # in review, not yet resolved): 6 pipeline CronJobs aren't matched by any
    # of the three groups below and go unwatched — mp-poller-price-anomaly,
    # mp-pantry-expire-recompute, mp-poller-recipe-review,
    # mp-score-review-sentiment, mp-summarize-reviews, mp-data-invariants.
    # "Reuse" isn't the same as "coverage verified" — folding these in needs
    # their real cadence confirmed first (not guessed), same as the three
    # existing groups were built from measured run history.
    CatalogMetric(
        metric_id="poller_stale",
        subject_type="cronjob",
        subject_labels=("namespace", "cronjob"),
        promql=(
            "(time() - kube_cronjob_status_last_successful_time{"
            "namespace=\"pipeline\", "
            "cronjob=~\"mp-poller-price-matview|mp-deal-pruner\"} > 10800)"
            " or (time() - kube_cronjob_status_last_successful_time{"
            "namespace=\"pipeline\", "
            "cronjob=~\"mp-poller-kurly|mp-poller-oasis-dawn|mp-poller-oasis-noon|"
            "mp-poller-deal-timesale|mp-poller-deal-closesale|mp-user-data-pruner|"
            "mp-chat-insights\"} > 108000)"
            " or (time() - kube_cronjob_status_last_successful_time{"
            "namespace=\"pipeline\", "
            "cronjob=~\"mp-poller-recipe|mp-poller-es-recipes\"} > 432000)"
        ),
        event=True,
    ),
    # Staleness alone can't catch a poller that exits 0 too fast to have done
    # its job — the 2026-08-04 Kurly incident (3,324 records became 96,
    # lastSuccessfulTime still updated, no alert fired). Reused verbatim from
    # the already-live MpKurlyCrawlTruncated PrometheusRule: normal Kurly
    # runs take 393-472s, a truncated one took 26s — 180s is the midpoint.
    # Still purely kube_job_status_* (kube-state-metrics), no app
    # instrumentation. Scoped to Kurly only, same as the source rule — Oasis/
    # recipe pollers are requests-based and raise on a block instead of
    # silently truncating, and deal-timesale/closesale normally run ~100s so
    # they'd false-positive on this threshold.
    CatalogMetric(
        metric_id="poller_kurly_truncated",
        subject_type="job",
        subject_labels=("namespace", "job_name"),
        promql=(
            "(kube_job_status_completion_time{namespace=\"pipeline\", "
            "job_name=~\"mp-poller-kurly-[0-9]+\"} "
            "- kube_job_status_start_time{namespace=\"pipeline\", "
            "job_name=~\"mp-poller-kurly-[0-9]+\"} < 180)"
            " and (time() - kube_job_status_completion_time{namespace=\"pipeline\", "
            "job_name=~\"mp-poller-kurly-[0-9]+\"} < 7200)"
        ),
        event=True,
    ),
)

P95_REQUEST_RATE_PROMQL = (
    "sum by(service) "
    "(rate(http_request_duration_highr_seconds_count{namespace=\"app\"}[5m]))"
)
