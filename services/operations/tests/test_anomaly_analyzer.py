from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.anomaly_analyzer import AnomalyAnalyzer
from app.models import AnalyzerConfig, EvaluationRequest, TimeSeriesPoint


START = datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc)


def _request(
    values: list[float],
    *,
    direction: str = "high",
    consecutive_windows: int = 3,
    rebaseline_after_windows: int = 30,
) -> EvaluationRequest:
    return EvaluationRequest(
        service="recipe",
        metric="p95_latency",
        points=[
            TimeSeriesPoint(
                timestamp=START + timedelta(minutes=index),
                value=value,
            )
            for index, value in enumerate(values)
        ],
        config=AnalyzerConfig(
            baseline_window=30,
            min_samples=30,
            z_threshold=3.0,
            mad_threshold=3.5,
            change_rate_threshold=0.25,
            consecutive_windows=consecutive_windows,
            rebaseline_after_windows=rebaseline_after_windows,
            direction=direction,
        ),
    )


def test_returns_insufficient_data_before_baseline_is_ready():
    result = AnomalyAnalyzer().evaluate(_request([100.0] * 20))

    assert result.status == "insufficient_data"
    assert result.available_samples == 20
    assert result.required_samples == 31


def test_normal_variation_does_not_create_anomaly():
    baseline = [98.0, 100.0, 102.0] * 10
    result = AnomalyAnalyzer().evaluate(
        _request(baseline + [99.0, 101.0, 100.0])
    )

    assert result.status == "normal"
    assert result.is_anomaly is False
    assert result.consecutive_breaches == 0
    assert result.breached_checks == []


def test_single_spike_remains_candidate():
    """A single moderate breach (not severe enough for the fast-track) still
    has to wait out consecutive_windows like before."""
    baseline = [98.0, 100.0, 102.0] * 10
    result = AnomalyAnalyzer().evaluate(_request(baseline + [107.0]))

    assert result.status == "candidate"
    assert result.is_anomaly is False
    assert result.consecutive_breaches == 1
    assert "z_score" in result.breached_checks
    assert result.promoted_via_severe_breach is False


def test_single_severe_spike_is_promoted_to_anomaly_immediately():
    """A single point far enough beyond the threshold (>= severe_breach_multiplier
    x z_threshold) does not have to wait out consecutive_windows — a service
    that looks dead should not take 3 minutes to be reported."""
    baseline = [98.0, 100.0, 102.0] * 10
    result = AnomalyAnalyzer().evaluate(_request(baseline + [180.0]))

    assert result.status == "anomaly"
    assert result.is_anomaly is True
    assert result.consecutive_breaches == 1
    assert result.promoted_via_severe_breach is True


def test_single_spike_followed_by_recovery_does_not_create_anomaly():
    baseline = [98.0, 100.0, 102.0] * 10
    result = AnomalyAnalyzer().evaluate(
        _request(baseline + [180.0, 100.0, 101.0])
    )

    assert result.status == "normal"
    assert result.is_anomaly is False
    assert result.consecutive_breaches == 0


def test_three_sustained_high_windows_create_anomaly():
    baseline = [98.0, 100.0, 102.0] * 10
    result = AnomalyAnalyzer().evaluate(
        _request(baseline + [130.0, 170.0, 220.0])
    )

    assert result.status == "anomaly"
    assert result.is_anomaly is True
    assert result.consecutive_breaches == 3
    assert result.current_value == 220.0
    assert result.baseline.sample_count == 30
    assert result.baseline.mean == pytest.approx(100.0)
    assert result.z_score is not None and result.z_score > 3.0


def test_low_direction_detects_sustained_traffic_drop():
    baseline = [98.0, 100.0, 102.0] * 10
    result = AnomalyAnalyzer().evaluate(
        _request(
            baseline + [70.0, 45.0, 20.0],
            direction="low",
        )
    )

    assert result.status == "anomaly"
    assert result.is_anomaly is True
    assert result.consecutive_breaches == 3


def test_sustained_breach_keeps_frozen_baseline_before_rebaseline_threshold():
    """Before rebaseline_after_windows, behavior matches the old frozen-baseline
    logic: a persisted breach must not dilute the baseline it is being judged
    against."""
    request = EvaluationRequest(
        service="recipe",
        metric="pod_memory_working_set",
        points=[
            TimeSeriesPoint(timestamp=START + timedelta(minutes=i), value=100.0)
            for i in range(5)
        ]
        + [
            TimeSeriesPoint(timestamp=START + timedelta(minutes=5 + i), value=300.0)
            for i in range(2)
        ],
        config=AnalyzerConfig(
            baseline_window=5,
            min_samples=5,
            z_threshold=3.0,
            mad_threshold=3.5,
            change_rate_threshold=0.5,
            consecutive_windows=2,
            rebaseline_after_windows=3,
        ),
    )
    result = AnomalyAnalyzer().evaluate(request)

    assert result.status == "anomaly"
    assert result.consecutive_breaches == 2
    assert result.baseline.mean == pytest.approx(100.0)


def test_sustained_level_shift_eventually_rebaselines_to_normal():
    """A metric that steps to a new, stable level and stays there must not be
    flagged as anomaly forever. Once the shift has persisted past
    rebaseline_after_windows, the new level is absorbed into the baseline and
    detection self-heals back to normal."""
    request = EvaluationRequest(
        service="recipe",
        metric="pod_memory_working_set",
        points=[
            TimeSeriesPoint(timestamp=START + timedelta(minutes=i), value=100.0)
            for i in range(5)
        ]
        + [
            TimeSeriesPoint(timestamp=START + timedelta(minutes=5 + i), value=300.0)
            for i in range(6)
        ],
        config=AnalyzerConfig(
            baseline_window=5,
            min_samples=5,
            z_threshold=3.0,
            mad_threshold=3.5,
            change_rate_threshold=0.5,
            consecutive_windows=2,
            rebaseline_after_windows=3,
        ),
    )
    result = AnomalyAnalyzer().evaluate(request)

    assert result.status == "normal"
    assert result.is_anomaly is False
    assert result.consecutive_breaches == 0
    # The baseline has absorbed the new level by now (no longer frozen at 100).
    assert result.baseline.mean == pytest.approx(220.0)


def test_persistently_worsening_metric_is_not_silenced_forever():
    """Rebaseline absorption is capped at baseline_window points per sustained
    breach. Without the cap, a metric that never actually levels off would
    drag the baseline along with it and its score would stay permanently
    suppressed. A metric that keeps escalating (here: 1.5x every window,
    far outrunning any baseline it could drag along) must keep reporting as
    anomaly, not silently reset to normal once absorption starts."""
    baseline = [100.0] * 5
    value = 100.0
    escalating = []
    for _ in range(40):
        value *= 1.5
        escalating.append(value)
    request = EvaluationRequest(
        service="recipe",
        metric="pod_memory_working_set",
        points=[
            TimeSeriesPoint(timestamp=START + timedelta(minutes=i), value=v)
            for i, v in enumerate(baseline + escalating)
        ],
        config=AnalyzerConfig(
            baseline_window=5,
            min_samples=5,
            z_threshold=3.0,
            mad_threshold=3.5,
            change_rate_threshold=0.5,
            consecutive_windows=2,
            rebaseline_after_windows=3,
        ),
    )
    result = AnomalyAnalyzer().evaluate(request)

    assert result.status == "anomaly"
    assert result.consecutive_breaches == len(escalating)
    assert result.baseline_recently_rebaselined is True


def test_gradual_drift_undetected_by_z_score_or_mad_is_caught_by_drift_check():
    """z_score/mad/change_rate all compare the current point against a
    baseline that keeps absorbing non-breaching points. A slow, steady climb
    never produces a single point large enough to breach any of the three —
    each step's move is small relative to the window it just got absorbed
    into — so the baseline just follows it upward indefinitely and nothing
    ever fires. This reproduces exactly that: a linear ramp of +0.35/step on
    top of the same oscillating pattern used elsewhere in this file, tuned
    so z_score/mad never cross their thresholds even once, yet the fixed
    seed baseline vs. current baseline comparison accumulates past
    change_rate_threshold and confirms over consecutive_windows."""
    pattern = [98.0, 100.0, 102.0]
    seed = pattern * 10
    drift = 0.35
    ramp = [pattern[i % 3] + drift * (i + 1) for i in range(90)]
    result = AnomalyAnalyzer().evaluate(_request(seed + ramp))

    assert result.status == "anomaly"
    assert result.breached_checks == ["drift"]
    assert result.z_score is not None and result.z_score < 3.0
    assert result.mad_score is not None and result.mad_score < 3.5


def test_normal_oscillation_never_triggers_drift():
    baseline = [98.0, 100.0, 102.0] * 10
    result = AnomalyAnalyzer().evaluate(
        _request(baseline + [99.0, 101.0, 100.0] * 20)
    )

    assert result.status == "normal"
    assert "drift" not in result.breached_checks


def test_baseline_recently_rebaselined_is_false_for_genuinely_calm_series():
    baseline = [98.0, 100.0, 102.0] * 10
    result = AnomalyAnalyzer().evaluate(
        _request(baseline + [99.0, 101.0, 100.0])
    )

    assert result.status == "normal"
    assert result.baseline_recently_rebaselined is False


def test_baseline_recently_rebaselined_is_true_after_absorbing_a_sustained_shift():
    """A 'normal' result reached via rebaseline absorption must be
    distinguishable from one that was always calm — otherwise 'recovered'
    and 'detection gave up watching a sustained breach' look identical."""
    request = EvaluationRequest(
        service="recipe",
        metric="pod_memory_working_set",
        points=[
            TimeSeriesPoint(timestamp=START + timedelta(minutes=i), value=100.0)
            for i in range(5)
        ]
        + [
            TimeSeriesPoint(timestamp=START + timedelta(minutes=5 + i), value=300.0)
            for i in range(6)
        ],
        config=AnalyzerConfig(
            baseline_window=5,
            min_samples=5,
            z_threshold=3.0,
            mad_threshold=3.5,
            change_rate_threshold=0.5,
            consecutive_windows=2,
            rebaseline_after_windows=3,
        ),
    )
    result = AnomalyAnalyzer().evaluate(request)

    assert result.status == "normal"
    assert result.baseline_recently_rebaselined is True


def test_rebaseline_after_windows_must_not_be_less_than_consecutive_windows():
    with pytest.raises(ValidationError, match="rebaseline_after_windows"):
        AnalyzerConfig(consecutive_windows=5, rebaseline_after_windows=2)


def test_flat_baseline_ignores_small_relative_move():
    """A near-constant baseline has ~0 dispersion, so z/mad scores are
    undefined. Sub-precision jitter must not be treated as a breach just
    because it's technically nonzero."""
    baseline = [100.0] * 30
    result = AnomalyAnalyzer().evaluate(_request(baseline + [100.2]))

    assert result.status == "normal"
    assert result.breached_checks == []


def test_flat_baseline_flags_large_relative_move():
    """A move large enough relative to the (flat) baseline still counts as a
    breach, gated on the existing change_rate_threshold rather than any
    nonzero difference."""
    baseline = [100.0] * 30
    result = AnomalyAnalyzer().evaluate(
        _request(baseline + [140.0, 140.0, 140.0])
    )

    assert result.status == "anomaly"
    assert "z_score" in result.breached_checks
    assert "mad" in result.breached_checks


def test_zero_baseline_still_flags_any_nonzero_move():
    """When the baseline itself is ~0 (e.g. an idle-at-0 queue), there is no
    meaningful relative ratio to gate on — any real nonzero move must still
    be caught, unlike the flat-but-nonzero case above."""
    baseline = [0.0] * 30
    result = AnomalyAnalyzer().evaluate(_request(baseline + [5.0, 5.0, 5.0]))

    assert result.status == "anomaly"
    assert result.consecutive_breaches == 3


def test_reproduces_real_low_traffic_cpu_jitter_as_normal():
    """Regression fixture from live cluster data: an idle pod's CPU usage
    wobbling by a thousandth of a percent must not be a severe anomaly."""
    baseline = [0.00172] * 30
    result = AnomalyAnalyzer().evaluate(
        EvaluationRequest(
            service="recipe",
            metric="pod_cpu_usage",
            points=[
                TimeSeriesPoint(timestamp=START + timedelta(minutes=i), value=v)
                for i, v in enumerate(baseline + [0.00176])
            ],
            config=AnalyzerConfig(),  # production defaults (change_rate_threshold=0.5)
        )
    )

    assert result.status == "normal"


def test_points_must_be_in_timestamp_order():
    with pytest.raises(ValidationError, match="ordered by timestamp"):
        EvaluationRequest(
            service="recipe",
            metric="p95_latency",
            points=[
                TimeSeriesPoint(timestamp=START + timedelta(minutes=1), value=100),
                TimeSeriesPoint(timestamp=START, value=101),
            ],
        )
