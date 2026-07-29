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
    direction: MetricDirection = "high"

    @model_validator(mode="after")
    def validate_window_sizes(self) -> "AnalyzerConfig":
        if self.min_samples > self.baseline_window:
            raise ValueError("min_samples must not exceed baseline_window")
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


class InsufficientDataResult(BaseModel):
    service: str
    metric: str
    status: Literal["insufficient_data"] = "insufficient_data"
    is_anomaly: Literal[False] = False
    available_samples: int
    required_samples: int


AnomalyEvaluation = EvaluationResult | InsufficientDataResult
