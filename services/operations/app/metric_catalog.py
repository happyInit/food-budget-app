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
    # An outright failure (non-zero exit) is the plainest signal of all —
    # no threshold to reuse or invent, just kube_job_status_failed itself
    # (0/1, kube-state-metrics, no app instrumentation). This is the same
    # metric behind kube-prometheus-stack's default KubeJobFailed rule,
    # which the mealplanning-config monitoring notes record as already
    # having caught a Kurly failure on 2026-07-30 (invisible only because
    # nothing routed it to Slack at the time). Confirmed live: mp-poller-
    # kurly-29773110 currently shows failed=1, reason="BackoffLimitExceeded"
    # — the same #627 incident poller_stale/poller_kurly_truncated target.
    # Scoped to the whole pipeline namespace, not just Kurly — an outright
    # job failure isn't a Kurly-specific failure mode the way silent
    # truncation is.
    CatalogMetric(
        metric_id="poller_job_failed",
        subject_type="job",
        subject_labels=("namespace", "job_name"),
        promql="kube_job_status_failed{namespace=\"pipeline\"} > 0",
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
    # static threshold instead. 85% is the common industry convention for "sustained
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
