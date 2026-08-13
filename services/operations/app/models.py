from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


MetricDirection = Literal["high", "low", "both"]
EvaluationStatus = Literal["insufficient_data", "normal", "candidate", "anomaly"]


class TimeSeriesPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    value: float = Field(allow_inf_nan=False)


class AnalyzerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_window: int = Field(default=60, ge=5, le=1440)
    min_samples: int = Field(default=30, ge=5, le=1440)
    z_threshold: float = Field(default=3.0, gt=0)
    mad_threshold: float = Field(default=3.5, gt=0)
    change_rate_threshold: float = Field(default=0.5, gt=0)
    consecutive_windows: int = Field(default=3, ge=1, le=10)
    # consecutive_windows exists to protect against a momentary blip being
    # mistaken for an incident. But it also means a real, short-lived
    # outage (shorter than consecutive_windows) never gets confirmed and
    # stays invisible to the investigation queue. Rather than lowering
    # consecutive_windows globally (which would make ordinary noise easier
    # to misclassify too), a single point whose deviation is this many
    # times the normal threshold skips the wait entirely — reuses
    # z_threshold/mad_threshold/change_rate_threshold scaled by this
    # multiplier, no new standalone threshold invented.
    severe_breach_multiplier: float = Field(default=2.0, gt=1.0)
    # A breach is normally excluded from the baseline so a real incident
    # cannot drag the baseline toward itself. Without a limit, a sustained
    # level shift (or a series flat enough that any move looks significant)
    # freezes the baseline forever and keeps re-triggering indefinitely.
    # After this many consecutive breach windows, the new level is accepted
    # into the baseline so detection can re-normalize. Default of 30 is not
    # derived from min_samples — it happens to share the same value, but the
    # two settings are independent and a metric overriding one does not move
    # the other.
    rebaseline_after_windows: int = Field(default=30, ge=1, le=1440)
    direction: MetricDirection = "high"

    @model_validator(mode="after")
    def validate_window_sizes(self) -> "AnalyzerConfig":
        if self.min_samples > self.baseline_window:
            raise ValueError("min_samples must not exceed baseline_window")
        if self.rebaseline_after_windows < self.consecutive_windows:
            raise ValueError(
                "rebaseline_after_windows must not be less than consecutive_windows"
            )
        return self


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str = Field(min_length=1, max_length=100)
    metric: str = Field(min_length=1, max_length=100)
    points: list[TimeSeriesPoint]
    config: AnalyzerConfig = Field(default_factory=AnalyzerConfig)

    @model_validator(mode="after")
    def validate_point_order(self) -> "EvaluationRequest":
        timestamps = [point.timestamp for point in self.points]
        if timestamps != sorted(timestamps):
            raise ValueError("points must be ordered by timestamp")
        if len(timestamps) != len(set(timestamps)):
            raise ValueError("point timestamps must be unique")
        return self


class BaselineStats(BaseModel):
    sample_count: int
    mean: float
    standard_deviation: float
    median: float
    mad: float


class EvaluationResult(BaseModel):
    service: str
    metric: str
    evaluated_at: datetime
    status: EvaluationStatus
    is_anomaly: bool
    current_value: float
    previous_value: float
    baseline: BaselineStats
    z_score: float | None
    mad_score: float | None
    change_rate: float | None
    breached_checks: list[str]
    consecutive_breaches: int
    required_consecutive_windows: int
    # True when the baseline this point was judged against contains values
    # accepted via rebaseline_after_windows rather than genuine calm — lets
    # a "normal" result be told apart from "detection gave up watching a
    # sustained breach", which look identical without this flag.
    baseline_recently_rebaselined: bool = False
    # True when status became "anomaly" because the latest point alone was
    # severe (>= severe_breach_multiplier x threshold), not because
    # consecutive_windows worth of confirmation was reached. Without this,
    # a genuinely dead service reported after one point looks identical to
    # one confirmed over consecutive_windows, and consecutive_breaches (1)
    # would otherwise look like an under-confirmed reading rather than a
    # deliberate fast-track.
    promoted_via_severe_breach: bool = False


class InsufficientDataResult(BaseModel):
    service: str
    metric: str
    status: Literal["insufficient_data"] = "insufficient_data"
    is_anomaly: Literal[False] = False
    available_samples: int
    required_samples: int


AnomalyEvaluation = EvaluationResult | InsufficientDataResult


class CollectorRunResult(BaseModel):
    collected_series: int
    evaluated_series: int
    skipped_series: int
    stored_candidates: int
    event_candidates: int
    errors: int


class AlertmanagerAlert(BaseModel):
    """The Alertmanager webhook fields required by Operations.

    Alertmanager may add fields between versions, so the boundary model ignores
    unknown fields while retaining labels and annotations as evidence.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    generator_url: str | None = Field(default=None, alias="generatorURL")
    fingerprint: str | None = None


class AlertmanagerWebhook(BaseModel):
    """Alertmanager webhook contract received by the Operations service."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    version: str
    group_key: str = Field(alias="groupKey")
    status: Literal["firing", "resolved"]
    receiver: str
    group_labels: dict[str, str] = Field(default_factory=dict, alias="groupLabels")
    common_labels: dict[str, str] = Field(default_factory=dict, alias="commonLabels")
    common_annotations: dict[str, str] = Field(
        default_factory=dict, alias="commonAnnotations"
    )
    external_url: str | None = Field(default=None, alias="externalURL")
    alerts: list[AlertmanagerAlert] = Field(min_length=1)


class NormalizedAlert(BaseModel):
    """Stable alert shape consumed by persistence and Incident correlation."""

    alert_id: str
    source: Literal["alertmanager"] = "alertmanager"
    status: Literal["firing", "resolved"]
    alert_name: str
    service: str
    severity: str
    starts_at: datetime
    ends_at: datetime | None = None
    received_at: datetime
    pod: str | None = None
    container: str | None = None
    labels: dict[str, str]
    annotations: dict[str, str]
    generator_url: str | None = None


class AlertIngestionResult(BaseModel):
    group_key: str
    receiver: str
    received_alert_count: int
    alerts: list[NormalizedAlert]
    incident_count: int = 0
    incidents: list["IncidentCandidate"] = Field(default_factory=list)


class ServiceDependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upstream: str = Field(min_length=1, max_length=100)
    downstream: str = Field(min_length=1, max_length=100)


class CorrelationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_window_minutes: int = Field(default=15, ge=1, le=120)
    dependencies: list[ServiceDependency] = Field(default_factory=list)


class IncidentCorrelationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alerts: list[NormalizedAlert] = Field(min_length=1)
    config: CorrelationConfig = Field(default_factory=CorrelationConfig)


class IncidentCandidate(BaseModel):
    incident_id: str
    status: Literal["open"] = "open"
    title: str
    first_seen_at: datetime
    last_seen_at: datetime
    earliest_alert_id: str
    earliest_alert_name: str
    suspected_origin_service: str
    affected_services: list[str]
    alert_count: int
    grouping_reasons: list[str]
    alerts: list[NormalizedAlert]


class IncidentCorrelationResult(BaseModel):
    incident_count: int
    incidents: list[IncidentCandidate]


class StoredAnomalyCandidate(BaseModel):
    metric_id: str
    subject_type: str
    subject_key: str
    labels: dict[str, str]
    evaluated_at: datetime
    status: Literal["candidate", "anomaly"]
    current_value: float
    baseline: BaselineStats | None = None
    z_score: float | None = None
    mad_score: float | None = None
    change_rate: float | None = None
    breached_checks: list[str] = Field(default_factory=list)
    consecutive_breaches: int
    required_consecutive_windows: int
    event_count: float | None = None


class EvidenceAnomaly(StoredAnomalyCandidate):
    selection_reasons: list[str]


class EvidenceSourceStatus(BaseModel):
    source: Literal["logs", "traces", "kubernetes_events", "deployments"]
    status: Literal["not_connected"] = "not_connected"
    message: str


class KubernetesEventEvidence(BaseModel):
    namespace: str
    event_id: str
    reason: str
    message: str
    event_type: str | None = None
    occurred_at: datetime
    count: int = Field(ge=1)
    pod: str | None = None
    selection_reasons: list[str]


class DeploymentEvidence(BaseModel):
    namespace: str
    deployment: str
    replica_set: str | None = None
    image: str
    image_tag: str | None = None
    git_sha: str | None = None
    observed_generation: int | None = None
    created_at: datetime
    selection_reasons: list[str]


class LogPatternEvidence(BaseModel):
    """Aggregated error log pattern, not a raw log dump."""

    namespace: str
    container: str
    pattern: str
    count: int = Field(ge=1)
    first_seen_at: datetime
    last_seen_at: datetime
    samples: list[str]
    selection_reasons: list[str]


class TraceEvidence(BaseModel):
    trace_id: str
    root_service: str | None = None
    duration_ms: float = Field(ge=0)
    has_error: bool
    span_count: int = Field(ge=1)
    started_at: datetime
    selection_reasons: list[str]


class EvidencePackage(BaseModel):
    """Deterministic incident-scoped input for a later Bedrock RCA request."""

    incident: IncidentCandidate
    generated_at: datetime
    selection_window_start: datetime
    selection_window_end: datetime
    anomalies: list[EvidenceAnomaly]
    alerts: list[NormalizedAlert]
    logs: list[LogPatternEvidence] = Field(default_factory=list)
    traces: list[TraceEvidence] = Field(default_factory=list)
    kubernetes_events: list[KubernetesEventEvidence] = Field(default_factory=list)
    deployments: list[DeploymentEvidence] = Field(default_factory=list)
    unavailable_sources: list[EvidenceSourceStatus] = Field(default_factory=list)


class EvidenceSnapshot(BaseModel):
    """Immutable EvidencePackage capture retained for incident investigation."""

    snapshot_id: str
    incident_id: str
    captured_at: datetime
    package: EvidencePackage
