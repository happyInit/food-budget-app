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
    baseline = [98.0, 100.0, 102.0] * 10
    result = AnomalyAnalyzer().evaluate(_request(baseline + [180.0]))

    assert result.status == "candidate"
    assert result.is_anomaly is False
    assert result.consecutive_breaches == 1
    assert {"z_score", "mad", "change_rate"} <= set(result.breached_checks)


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
