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
)

P95_REQUEST_RATE_PROMQL = (
    "sum by(service) "
    "(rate(http_request_duration_highr_seconds_count{namespace=\"app\"}[5m]))"
)
