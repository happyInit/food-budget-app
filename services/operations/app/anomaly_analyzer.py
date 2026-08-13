from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median, pstdev

from app.models import (
    AnalyzerConfig,
    AnomalyEvaluation,
    BaselineStats,
    EvaluationRequest,
    EvaluationResult,
    InsufficientDataResult,
)

_ROBUST_Z_SCALE = 0.6745
_ZERO_TOLERANCE = 1e-12


@dataclass(frozen=True)
class _PointEvaluation:
    baseline: BaselineStats
    z_score: float | None
    mad_score: float | None
    change_rate: float | None
    breached_checks: tuple[str, ...]

    @property
    def is_breach(self) -> bool:
        return bool(self.breached_checks)


class AnomalyAnalyzer:
    """Evaluate the latest point against rolling historical baselines."""

    def evaluate(self, request: EvaluationRequest) -> AnomalyEvaluation:
        config = request.config
        required_samples = config.min_samples + 1
        if len(request.points) < required_samples:
            return InsufficientDataResult(
                service=request.service,
                metric=request.metric,
                available_samples=len(request.points),
                required_samples=required_samples,
            )

        point_evaluations: list[_PointEvaluation] = []
        accepted_baseline_values = [
            point.value for point in request.points[: config.min_samples]
        ]
        breach_streak = 0
        for index in range(config.min_samples, len(request.points)):
            baseline_values = accepted_baseline_values[-config.baseline_window :]
            current = request.points[index].value
            previous = request.points[index - 1].value
            point_evaluation = self._evaluate_point(
                baseline_values=baseline_values,
                current=current,
                previous=previous,
                config=config,
            )
            point_evaluations.append(point_evaluation)
            if point_evaluation.is_breach:
                breach_streak += 1
            else:
                breach_streak = 0
            # A breach is excluded from the baseline so a real, short-lived
            # incident cannot drag the baseline toward itself while it is
            # still being investigated. But excluding every breach forever
            # means a baseline that is stale (a level shift, or a series so
            # flat that any move looks significant) can never re-normalize —
            # the same sustained value keeps re-triggering with a growing
            # score indefinitely. Once a breach has persisted for
            # rebaseline_after_windows, treat it as the new normal and let
            # the baseline start absorbing it again.
            if not point_evaluation.is_breach or breach_streak >= config.rebaseline_after_windows:
                accepted_baseline_values.append(current)

        consecutive_breaches = 0
        for evaluation in reversed(point_evaluations):
            if not evaluation.is_breach:
                break
            consecutive_breaches += 1

        latest = point_evaluations[-1]
        is_anomaly = consecutive_breaches >= config.consecutive_windows
        if is_anomaly:
            status = "anomaly"
        elif latest.is_breach:
            status = "candidate"
        else:
            status = "normal"

        return EvaluationResult(
            service=request.service,
            metric=request.metric,
            evaluated_at=request.points[-1].timestamp,
            status=status,
            is_anomaly=is_anomaly,
            current_value=request.points[-1].value,
            previous_value=request.points[-2].value,
            baseline=latest.baseline,
            z_score=latest.z_score,
            mad_score=latest.mad_score,
            change_rate=latest.change_rate,
            breached_checks=list(latest.breached_checks),
            consecutive_breaches=consecutive_breaches,
            required_consecutive_windows=config.consecutive_windows,
        )

    def _evaluate_point(
        self,
        *,
        baseline_values: list[float],
        current: float,
        previous: float,
        config: AnalyzerConfig,
    ) -> _PointEvaluation:
        baseline_mean = sum(baseline_values) / len(baseline_values)
        baseline_stddev = pstdev(baseline_values)
        baseline_median = median(baseline_values)
        absolute_deviations = [
            abs(value - baseline_median) for value in baseline_values
        ]
        baseline_mad = median(absolute_deviations)

        z_score = self._standard_score(current, baseline_mean, baseline_stddev)
        mad_score = self._mad_score(current, baseline_median, baseline_mad)
        change_rate = self._change_rate(current, previous)

        breached_checks: list[str] = []
        if self._score_breached(
            score=z_score,
            difference=current - baseline_mean,
            dispersion=baseline_stddev,
            threshold=config.z_threshold,
            direction=config.direction,
        ):
            breached_checks.append("z_score")
        if self._score_breached(
            score=mad_score,
            difference=current - baseline_median,
            dispersion=baseline_mad,
            threshold=config.mad_threshold,
            direction=config.direction,
        ):
            breached_checks.append("mad")
        if change_rate is not None and self._directional_value(
            change_rate, config.direction
        ) >= config.change_rate_threshold:
            breached_checks.append("change_rate")

        return _PointEvaluation(
            baseline=BaselineStats(
                sample_count=len(baseline_values),
                mean=baseline_mean,
                standard_deviation=baseline_stddev,
                median=baseline_median,
                mad=baseline_mad,
            ),
            z_score=z_score,
            mad_score=mad_score,
            change_rate=change_rate,
            breached_checks=tuple(breached_checks),
        )

    @staticmethod
    def _standard_score(
        current: float, baseline_mean: float, baseline_stddev: float
    ) -> float | None:
        if baseline_stddev <= _ZERO_TOLERANCE:
            return None
        return (current - baseline_mean) / baseline_stddev

    @staticmethod
    def _mad_score(
        current: float, baseline_median: float, baseline_mad: float
    ) -> float | None:
        if baseline_mad <= _ZERO_TOLERANCE:
            return None
        return _ROBUST_Z_SCALE * (current - baseline_median) / baseline_mad

    @staticmethod
    def _change_rate(current: float, previous: float) -> float | None:
        if math.isclose(previous, 0.0, abs_tol=_ZERO_TOLERANCE):
            return None
        return (current - previous) / abs(previous)

    @classmethod
    def _score_breached(
        cls,
        *,
        score: float | None,
        difference: float,
        dispersion: float,
        threshold: float,
        direction: str,
    ) -> bool:
        if dispersion <= _ZERO_TOLERANCE:
            return (
                not math.isclose(difference, 0.0, abs_tol=_ZERO_TOLERANCE)
                and cls._directional_value(difference, direction) > 0
            )
        return score is not None and cls._directional_value(score, direction) >= threshold

    @staticmethod
    def _directional_value(value: float, direction: str) -> float:
        if direction == "high":
            return value
        if direction == "low":
            return -value
        return abs(value)
