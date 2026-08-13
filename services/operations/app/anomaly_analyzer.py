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
    baseline_recently_rebaselined: bool = False

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
        # Parallel to accepted_baseline_values: whether that entry was
        # accepted because it wasn't a breach (False) or force-absorbed after
        # a sustained breach (True). Lets a result say "this baseline recently
        # gave up watching a breach" instead of looking like genuine calm.
        accepted_baseline_forced = [False] * len(accepted_baseline_values)
        breach_streak = 0
        rebaseline_absorptions = 0
        for index in range(config.min_samples, len(request.points)):
            baseline_values = accepted_baseline_values[-config.baseline_window :]
            baseline_recently_rebaselined = any(
                accepted_baseline_forced[-config.baseline_window :]
            )
            current = request.points[index].value
            previous = request.points[index - 1].value
            point_evaluation = self._evaluate_point(
                baseline_values=baseline_values,
                baseline_recently_rebaselined=baseline_recently_rebaselined,
                current=current,
                previous=previous,
                config=config,
            )
            point_evaluations.append(point_evaluation)
            if point_evaluation.is_breach:
                breach_streak += 1
            else:
                breach_streak = 0
                rebaseline_absorptions = 0
            # A breach is excluded from the baseline so a real, short-lived
            # incident cannot drag the baseline toward itself while it is
            # still being investigated. But excluding every breach forever
            # means a baseline that is stale (a level shift, or a series so
            # flat that any move looks significant) can never re-normalize —
            # the same sustained value keeps re-triggering with a growing
            # score indefinitely. Once a breach has persisted for
            # rebaseline_after_windows, treat it as the new normal and let
            # the baseline start absorbing it again — but only up to
            # baseline_window points per sustained-breach event. Without a
            # cap, a metric that never actually stabilizes (steadily worsens
            # rather than levelling off) would drag the baseline along with
            # it forever, permanently suppressing its own score. Once the cap
            # is hit the baseline freezes again and a still-unresolved breach
            # goes back to being reported as an anomaly instead of silently
            # tracked.
            if not point_evaluation.is_breach:
                accepted_baseline_values.append(current)
                accepted_baseline_forced.append(False)
            elif (
                breach_streak >= config.rebaseline_after_windows
                and rebaseline_absorptions < config.baseline_window
            ):
                accepted_baseline_values.append(current)
                accepted_baseline_forced.append(True)
                rebaseline_absorptions += 1

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
            baseline_recently_rebaselined=latest.baseline_recently_rebaselined,
        )

    def _evaluate_point(
        self,
        *,
        baseline_values: list[float],
        baseline_recently_rebaselined: bool,
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
            reference=baseline_mean,
            threshold=config.z_threshold,
            change_rate_threshold=config.change_rate_threshold,
            direction=config.direction,
        ):
            breached_checks.append("z_score")
        if self._score_breached(
            score=mad_score,
            difference=current - baseline_median,
            dispersion=baseline_mad,
            reference=baseline_median,
            threshold=config.mad_threshold,
            change_rate_threshold=config.change_rate_threshold,
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
            baseline_recently_rebaselined=baseline_recently_rebaselined,
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
        reference: float,
        threshold: float,
        change_rate_threshold: float,
        direction: str,
    ) -> bool:
        if dispersion <= _ZERO_TOLERANCE:
            # No meaningful variance to compute a standard/robust z-score
            # against (a near-constant baseline). A z/mad score is undefined
            # here, so falling back to "any nonzero move is a breach" makes
            # sub-precision jitter on a flat metric (e.g. 0.17% CPU wobbling
            # by a thousandth of a point) register as a severe anomaly.
            # Gate on relative size instead, reusing the already-configured
            # change_rate_threshold — unless the baseline itself is ~0
            # (e.g. an idle-at-0 queue), where no relative ratio exists and
            # any real nonzero move is significant on its own.
            if math.isclose(reference, 0.0, abs_tol=_ZERO_TOLERANCE):
                return (
                    not math.isclose(difference, 0.0, abs_tol=_ZERO_TOLERANCE)
                    and cls._directional_value(difference, direction) > 0
                )
            relative_change = abs(difference) / abs(reference)
            return (
                relative_change >= change_rate_threshold
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
