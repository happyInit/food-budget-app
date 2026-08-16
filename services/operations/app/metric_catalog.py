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
    # SYMPTOM alerts, reused from the already-live mp-app-symptom
    # PrometheusRule (mealplanning-config monitoring/base/rules-app-symptom.yaml).
    # Distinct from every CAUSE-style entry above: those watch resource/
    # component state, these watch specific user journeys directly —
    # written after a real incident (2026-08-03) where nori analyzer
    # breakage made Korean search return 0 results while every CAUSE alarm
    # (pods Ready, CPU/memory normal, HTTP 200) stayed silent.
    #
    # Absolute counts over a long window, not ratios — the source file's own
    # header explains why: at this traffic level (mealplan ~58 req/24h) one
    # error is already a 1.7% ratio, and a 5% ratio alarm would fire on 3
    # errors while staying silent entirely when the denominator is 0 in a
    # quiet window. 4xx is deliberately excluded too (account's baseline 401
    # rate is 42.8% — expired tokens/anonymous access mixed in normally).
    # Confirmed live before adding: 0 5xx responses in the last 24h, so none
    # of this fires as a false positive on day one.
    CatalogMetric(
        metric_id="auth_path_failing",
        subject_type="app_symptom",
        subject_labels=(),
        promql=(
            "min_over_time((sum(increase(http_requests_total{namespace=\"app\","
            "service!~\".*-canary\","
            "handler=~\"/api/auth/(login|signup|refresh|google|kakao)\","
            "status=~\"5..\"}[30m])) >= bool 5)[15m:1m]) == 1"
        ),
        event=True,
    ),
    CatalogMetric(
        metric_id="mealplan_recommend_failing",
        subject_type="app_symptom",
        subject_labels=(),
        promql=(
            "min_over_time((sum(increase(http_requests_total{namespace=\"app\","
            "service!~\".*-canary\",handler=\"/api/mealplan/recommend\","
            "status=~\"5..\"}[30m])) >= bool 3)[15m:1m]) == 1"
        ),
        event=True,
    ),
    CatalogMetric(
        metric_id="app_errors_accumulating",
        subject_type="service",
        subject_labels=("service",),
        promql=(
            "min_over_time((sum by (service) (increase(http_requests_total{"
            "namespace=\"app\",service!~\".*-canary\",status=~\"5..\"}[30m])) "
            ">= bool 10)[30m:1m]) == 1"
        ),
        event=True,
    ),
    # Near-OOM early warning, complementary to pod_oom_killed above — that
    # one only fires after a pod has already died; this one watches the
    # ratio to its own memory limit, catching the run-up beforehand.
    # container_memory_working_set_bytes/limit as a *ratio* is a different
    # signal than pod_memory_working_set's absolute-bytes floor elsewhere in
    # this catalog — a pod near its own limit matters regardless of whether
    # that limit is big or small in absolute terms.
    CatalogMetric(
        metric_id="container_memory_near_limit",
        subject_type="pod_container",
        subject_labels=("namespace", "pod", "container"),
        promql=(
            "container_memory_working_set_bytes{container!=\"\", "
            "container!=\"POD\", container!=\"elasticsearch\"} "
            "/ on(namespace, pod, container) "
            "kube_pod_container_resource_limits{resource=\"memory\"} > 0.85"
        ),
        event=True,
    ),
    # ES runs hot by design (~87% resident is normal) — 85% would be
    # permanent noise, so this uses a separate, higher 90% threshold scoped
    # to the elasticsearch container specifically (same source-file
    # reasoning as elasticsearch_heap_high's own threshold above, but this
    # one watches container memory against its K8s limit, not JVM heap
    # against JVM's own max — different failure mode: this catches "about to
    # be OOMKilled by the kubelet", heap_high catches "JVM itself is under
    # pressure").
    CatalogMetric(
        metric_id="elasticsearch_memory_near_limit",
        subject_type="pod_container",
        subject_labels=("namespace", "pod", "container"),
        promql=(
            "container_memory_working_set_bytes{container=\"elasticsearch\"} "
            "/ on(namespace, pod, container) "
            "kube_pod_container_resource_limits{resource=\"memory\"} > 0.90"
        ),
        event=True,
    ),
    # Canary rollout health, reused from the already-live mp-rollouts
    # PrometheusRule (mealplanning-config monitoring/base/rules-rollouts.yaml).
    # Confirmed live before adding: mp-account and mp-recipe are both
    # currently phase=Completed (healthy) — the other five phase series per
    # rollout all read 0, so nothing here fires as a false positive on day
    # one.
    #
    # 🔴 Label trap documented in the source file, carried over here: the
    # rollout_phase metric's own `namespace` label is always "argo-rollouts"
    # (the ServiceMonitor's scrape-target namespace overwrites it — the real
    # app namespace survives only as exported_namespace, unused here).
    # Identify by `name`, not namespace — filtering on namespace="app" would
    # never fire.
    #
    # rollout_phase is a 6-way gauge (Abort/Completed/Error/Paused/
    # Progressing/Timeout) — exactly one phase is 1 per rollout at a time —
    # so "== 1" picks the current state directly, not a rate or increase.
    # As with the data-tier entries, sustained-duration Alertmanager `for:`
    # is approximated with min_over_time(...) == 1 requiring the phase to
    # hold for every sample in the window, not just right now.
    CatalogMetric(
        metric_id="rollout_aborted",
        subject_type="rollout",
        subject_labels=("name",),
        promql="min_over_time(rollout_phase{phase=\"Abort\"}[2m]) == 1",
        event=True,
    ),
    # HA 2-replica controller; only fires when all of it is gone (absent()
    # covers the target vanishing entirely, same pattern as
    # backup_probe_missing/elasticsearch_metrics_unavailable — up==0 alone
    # goes silent too if the scrape target disappears rather than just
    # failing).
    CatalogMetric(
        metric_id="rollouts_controller_down",
        subject_type="rollouts_controller",
        subject_labels=(),
        promql=(
            "absent(up{job=\"rollouts-argo-rollouts-metrics\"}) "
            "or max(up{job=\"rollouts-argo-rollouts-metrics\"}) == 0"
        ),
        event=True,
    ),
    CatalogMetric(
        metric_id="rollout_error",
        subject_type="rollout",
        subject_labels=("name", "phase"),
        promql=(
            "min_over_time(rollout_phase{phase=~\"Error|Timeout\"}[5m]) == 1"
        ),
        event=True,
    ),
    # 30m: measured normal canary duration is ~4-7min (20->50->100 with
    # automated analysis) — this is 4x+ headroom, catching a rollout that's
    # genuinely stuck (commonly: canary pod can't schedule/pull image) rather
    # than one still progressing normally.
    CatalogMetric(
        metric_id="rollout_stuck",
        subject_type="rollout",
        subject_labels=("name", "phase"),
        promql=(
            "min_over_time(rollout_phase{phase=~\"Paused|Progressing\"}[30m]) == 1"
        ),
        event=True,
    ),
    # Data-tier cluster health, reused from the already-live mp-data-tier
    # PrometheusRule (mealplanning-config monitoring/base/rules-data-tier.yaml,
    # "태현 소유" per its header). Confirmed live before adding: cluster is
    # currently green (the source file's own precondition — the recipes
    # index had to move off replica=0 first, or yellow is permanently true —
    # was already satisfied) and Kafka shows 3/3 brokers, 0 under-replicated
    # partitions.
    #
    # Sustained-duration alerts (Alertmanager's `for:`) don't have a direct
    # equivalent in Operations' per-cycle event check, so duration is baked
    # into the PromQL itself via *_over_time() instead — e.g. min_over_time
    # (...[30m]) == 1 requires the condition to hold for every sample across
    # the whole window, not just "currently true". Slightly stricter than the
    # source rule's "momentarily-true, sustained via for:" semantics, but the
    # same intent: don't fire on a single flaky scrape.
    #
    # "Watch the watcher" pattern, same as backup_probe_missing — if the
    # exporter/scrape path dies, the cluster-health checks below go silent
    # too, reading exactly like "everything is fine".
    CatalogMetric(
        metric_id="elasticsearch_metrics_unavailable",
        subject_type="elasticsearch_cluster",
        subject_labels=(),
        promql=(
            "absent(up{job=\"mp-elasticsearch-exporter\"}) "
            "or max(up{job=\"mp-elasticsearch-exporter\"}) == 0 "
            "or absent_over_time(elasticsearch_cluster_health_status{"
            "job=\"mp-elasticsearch-exporter\"}[10m])"
        ),
        event=True,
    ),
    CatalogMetric(
        metric_id="elasticsearch_cluster_yellow",
        subject_type="elasticsearch_cluster",
        subject_labels=(),
        promql=(
            "min_over_time(elasticsearch_cluster_health_status{"
            "color=\"yellow\"}[30m]) == 1"
        ),
        event=True,
    ),
    CatalogMetric(
        metric_id="elasticsearch_cluster_red",
        subject_type="elasticsearch_cluster",
        subject_labels=(),
        promql=(
            "min_over_time(elasticsearch_cluster_health_status{"
            "color=\"red\"}[5m]) == 1"
        ),
        event=True,
    ),
    CatalogMetric(
        metric_id="elasticsearch_disk_high",
        subject_type="elasticsearch_volume",
        subject_labels=("namespace", "persistentvolumeclaim"),
        promql=(
            "max by(namespace, persistentvolumeclaim) ("
            "1 - kubelet_volume_stats_available_bytes{namespace=\"data\", "
            "persistentvolumeclaim=~\"elasticsearch-data-es-.*\"} "
            "/ kubelet_volume_stats_capacity_bytes{namespace=\"data\", "
            "persistentvolumeclaim=~\"elasticsearch-data-es-.*\"}"
            ") > 0.85"
        ),
        event=True,
    ),
    CatalogMetric(
        metric_id="kafka_metrics_unavailable",
        subject_type="kafka_cluster",
        subject_labels=(),
        promql=(
            "absent(up{job=\"data/mp-kafka-exporter\"}) "
            "or max(up{job=\"data/mp-kafka-exporter\"}) == 0 "
            "or absent_over_time(kafka_brokers{job=\"data/mp-kafka-exporter\"}[10m]) "
            "or absent_over_time(kafka_topic_partition_under_replicated_partition{"
            "job=\"data/mp-kafka-exporter\"}[10m])"
        ),
        event=True,
    ),
    # 3-broker/RF=3 cluster. max_over_time < 3 over the full window means the
    # count never recovered to 3 anywhere in it — sustained low, not a single
    # dip.
    CatalogMetric(
        metric_id="kafka_broker_down",
        subject_type="kafka_cluster",
        subject_labels=("namespace", "pod"),
        promql="max_over_time(kafka_brokers{job=\"data/mp-kafka-exporter\"}[10m]) < 3",
        event=True,
    ),
    # One alert for the whole cluster (not per-partition) so a single broker
    # loss doesn't fire dozens of near-simultaneous entries — same
    # aggregation the source rule uses. min_over_time per partition requires
    # that partition to have stayed under-replicated for the entire window;
    # the outer max() catches if any partition qualifies.
    CatalogMetric(
        metric_id="kafka_isr_shrink",
        subject_type="kafka_cluster",
        subject_labels=(),
        promql=(
            "max(min_over_time(kafka_topic_partition_under_replicated_partition{"
            "job=\"data/mp-kafka-exporter\"}[10m])) > 0"
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
    # kube_node_status_condition is already a 0/1 gauge, not a rate or count —
    # there is no threshold to invent here, the condition itself is the
    # signal. min_over_time(...)[5m] instead of a bare instant check so a
    # single flaky scrape (kubelet momentarily unresponsive) doesn't read as
    # NotReady; same min_over_time-for-sustained-state pattern already used
    # elsewhere in this catalog (poller staleness, ES cluster color).
    CatalogMetric(
        metric_id="node_not_ready",
        subject_type="node",
        subject_labels=("node",),
        promql=(
            'min_over_time(kube_node_status_condition{'
            'condition="Ready", status="false"}[5m]) == 1'
        ),
        event=True,
    ),
    CatalogMetric(
        metric_id="node_disk_pressure",
        subject_type="node",
        subject_labels=("node",),
        promql=(
            'min_over_time(kube_node_status_condition{'
            'condition="DiskPressure", status="true"}[5m]) == 1'
        ),
        event=True,
    ),
    # Plain Deployments (the 7 rolling-strategy services, plus cluster
    # infra like coredns/cilium-operator/pg-pooler) don't emit anything
    # under Argo Rollouts' own metrics — rollout_stuck/rollout_aborted
    # elsewhere in this catalog only see the 2 canary services. Unavailable
    # replica count is itself the signal (0 vs not-0), no threshold to
    # invent. 10m sustained via subquery so an ordinary rolling-update
    # blip (a replica briefly unavailable while its pod restarts) doesn't
    # fire — mirrors the duration already used for MpESVolumeMetricsUnavailable
    # in mealplanning-config (15m) and the workload-spread rules (20m) for the
    # same "don't fire on a normal transient" reasoning, scaled down for a
    # simpler binary count with no missing-data risk.
    CatalogMetric(
        metric_id="deployment_replicas_unavailable",
        subject_type="deployment",
        subject_labels=("namespace", "deployment"),
        promql=(
            "min_over_time((kube_deployment_status_replicas_unavailable "
            "> bool 0)[10m:1m]) == 1"
        ),
        event=True,
    ),
    # Reuses the 85% threshold already proven in mealplanning-config's
    # MpESDiskHigh/MpMinIODiskHigh (rules-data-tier.yaml) rather than
    # inventing a new number — generalized here from those two specific
    # PVCs to every PVC in the cluster. 30m sustained matches those same
    # rules' `for: 30m`.
    CatalogMetric(
        metric_id="pvc_disk_high",
        subject_type="pvc",
        subject_labels=("namespace", "persistentvolumeclaim"),
        promql=(
            "min_over_time(((100 * (1 - kubelet_volume_stats_available_bytes "
            "/ kubelet_volume_stats_capacity_bytes)) > bool 85)[30m:1m]) == 1"
        ),
        event=True,
    ),
    # No existing Alertmanager rule for mesh-level 5xx to reuse — and unlike
    # the event metrics above, "normal" 5xx rate genuinely varies per
    # destination service, so a single static threshold would either miss
    # slow services or false-positive on naturally noisier ones. Same
    # shape as service_5xx_rate (zero-guard via `or on() 0 *`, denominator
    # check via `and on() > 0`) but reads Istio's own mesh telemetry
    # (reporter="destination") instead of the app's self-reported
    # http_requests_total — catches mesh-level failures (e.g. Istio circuit
    # breaking, upstream connection resets) that never reach the app's own
    # counters. No p95_request_rate_guard: istio_requests_total doesn't
    # carry a "service" label (it's destination_service_name), and the
    # PromQL's own `and on() > 0` denominator guard already excludes
    # zero-traffic series the same way service_5xx_rate's base query does.
    CatalogMetric(
        metric_id="mesh_5xx_rate",
        subject_type="istio_service",
        subject_labels=("destination_service_name",),
        promql=(
            "(100 * ("
            "(sum by(destination_service_name) (rate(istio_requests_total{"
            'reporter="destination", destination_service_namespace="app", '
            'response_code=~"5.."}[5m]))) '
            "or on(destination_service_name) (0 * sum by(destination_service_name) "
            "(rate(istio_requests_total{"
            'reporter="destination", destination_service_namespace="app"}[5m])))) '
            "/ sum by(destination_service_name) (rate(istio_requests_total{"
            'reporter="destination", destination_service_namespace="app"}[5m])))'
            ") and on(destination_service_name) (sum by(destination_service_name) "
            "(rate(istio_requests_total{"
            'reporter="destination", destination_service_namespace="app"}[5m])) > 0)'
        ),
    ),
    # Same reasoning as mesh_5xx_rate: CoreDNS SERVFAIL rate has no
    # cluster-proven static threshold to reuse, and "normal" varies with
    # query volume, so statistical detection over each CoreDNS pod's own
    # history fits better than a static number.
    CatalogMetric(
        metric_id="dns_servfail_rate",
        subject_type="coredns_instance",
        subject_labels=("namespace", "pod"),
        promql=(
            "(100 * ("
            "(sum by(namespace, pod) (rate(coredns_dns_responses_total{"
            'namespace="kube-system", rcode="SERVFAIL"}[5m]))) '
            "or on(namespace, pod) (0 * sum by(namespace, pod) "
            "(rate(coredns_dns_responses_total{"
            'namespace="kube-system"}[5m])))) '
            "/ sum by(namespace, pod) (rate(coredns_dns_responses_total{"
            'namespace="kube-system"}[5m])))'
            ") and on(namespace, pod) (sum by(namespace, pod) "
            "(rate(coredns_dns_responses_total{"
            'namespace="kube-system"}[5m])) > 0)'
        ),
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
    # Backup silently failing is the worst kind of gap — invisible until a
    # real disaster needs the backup that wasn't there. Thresholds are not
    # new: reused verbatim from the already-live mp-backup PrometheusRule
    # (mealplanning-config monitoring/base/rules-backup.yaml), whose own
    # header explains they were built from "each track's real cadence + one
    # missed cycle" (e.g. PG WAL archives every ~5min normally, 2700s =
    # 7+ misses). mp_backup_*_seconds/_success/_object_count come from a
    # timer + node-exporter textfile on the ops host (roles/backup_freshness)
    # — reading an existing metric, not new instrumentation for this
    # PR's purposes, though that textfile source is itself the "real"
    # instrumentation the source rule's header describes adding on 2026-08-03.
    #
    # Five staleness tracks combined into one entry the same way poller_stale
    # groups cadences — each track's own threshold, same pattern.
    CatalogMetric(
        metric_id="backup_stale",
        subject_type="backup_track",
        subject_labels=("track",),
        promql=(
            # WAL: archive_timeout 302s; 2700s = 7+ consecutive misses —
            # PITR chain breaks immediately, this is the RPO-critical one.
            "(time() - mp_backup_last_object_timestamp_seconds{track=\"pg_wal\"} > 2700)"
            # PG base: daily 03:00 KST; 108000s (30h) = missed a full day.
            " or (time() - mp_backup_last_object_timestamp_seconds{track=\"pg_base\"} > 108000)"
            # etcd snapshot: daily 02:00 KST; same 30h threshold.
            " or (time() - mp_backup_last_object_timestamp_seconds{track=\"etcd\"} > 108000)"
            # Secrets/PKI bundle: weekly; 777600s (9d) = 2 consecutive misses.
            " or (time() - mp_backup_last_object_timestamp_seconds{track=\"secrets\"} > 777600)"
            # Source mirror: monthly; 3024000s (35d) = missed a month.
            " or (time() - mp_backup_last_object_timestamp_seconds{track=\"source\"} > 3024000)"
        ),
        event=True,
    ),
    # The probe metric itself going missing silences every backup_stale check
    # above without looking like anything changed — "quiet = normal" reads
    # exactly like the failure mode it exists to catch. absent() naturally
    # fits the event pattern (emits a labelless 1-valued series only when the
    # metric doesn't exist at all).
    CatalogMetric(
        metric_id="backup_probe_missing",
        subject_type="backup_probe",
        subject_labels=(),
        promql="absent(mp_backup_check_timestamp_seconds)",
        event=True,
    ),
    # S3 lookup itself failing (bad credentials, revoked access, missing
    # bucket) usually breaks upload too and precedes staleness — catches it
    # sooner. mp_backup_check_success is 0/1; "== bool 0" keeps every
    # track's series (not just failing ones) but assigns 1 only where it's
    # actually 0, matching the event path's value>0-means-anomaly contract
    # without a raw 0-valued match getting silently skipped.
    CatalogMetric(
        metric_id="backup_probe_failed",
        subject_type="backup_track",
        subject_labels=("track",),
        promql="mp_backup_check_success == bool 0",
        event=True,
    ),
    # Release images are manual/irregular, so a staleness threshold would
    # cry wolf every quiet month — this checks "has anything ever landed
    # here", not "how recently". Same == bool 0 rewrite as above.
    CatalogMetric(
        metric_id="backup_image_never_archived",
        subject_type="backup_track",
        subject_labels=("track",),
        promql="mp_backup_object_count{track=\"image\"} == bool 0",
        event=True,
    ),
    # PG's in-cluster MinIO logical dump — not S3, so it isn't covered by
    # mp_backup_* above. It's a same-host convenience restore path (not DR:
    # MinIO lives on host B alone), watched via kube-state-metrics like
    # poller_stale/poller_kurly_truncated — no new instrumentation.
    CatalogMetric(
        metric_id="backup_pg_onsite_dump_stale",
        subject_type="cronjob",
        subject_labels=("namespace", "cronjob"),
        promql=(
            "time() - kube_cronjob_status_last_successful_time{"
            "namespace=\"data\", cronjob=\"mp-pg-onsite-dump\"} > 108000"
        ),
        event=True,
    ),
)

P95_REQUEST_RATE_PROMQL = (
    "sum by(service) "
    "(rate(http_request_duration_highr_seconds_count{namespace=\"app\"}[5m]))"
)
