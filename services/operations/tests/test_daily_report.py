from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.daily_report import DailySnapshot, ReportWindow, format_daily_report, format_threaded_daily_report


KST = ZoneInfo("Asia/Seoul")


def test_report_window_covers_previous_24_hours_in_kst():
    window = ReportWindow.ending_at(datetime(2026, 8, 18, 9, 5, tzinfo=KST))
    assert window.start == datetime(2026, 8, 17, 9, 0, tzinfo=KST)
    assert window.end == datetime(2026, 8, 18, 9, 0, tzinfo=KST)


def test_daily_report_keeps_missing_slo_and_source_failure_visible():
    window = ReportWindow(
        start=datetime(2026, 8, 17, 9, 0, tzinfo=KST),
        end=datetime(2026, 8, 18, 9, 0, tzinfo=KST),
    )
    payload = format_daily_report(
        DailySnapshot(2, 1, 3, None, None, ("Prometheus query failed: timeout",)),
        window,
        Settings(),
    )
    assert "🔴 조치 필요" in payload["text"]
    assert "SLO 미설정" in payload["text"]
    assert "데이터 없음" in payload["text"]
    assert "Prometheus query failed: timeout" in payload["text"]


def test_daily_report_includes_detailed_analysis_sections():
    window = ReportWindow(
        start=datetime(2026, 8, 17, 9, 0, tzinfo=KST),
        end=datetime(2026, 8, 18, 9, 0, tzinfo=KST),
    )
    payload = format_daily_report(
        DailySnapshot(
            1,
            0,
            4,
            99.99,
            420.0,
            incident_titles=("account p95 latency increase",),
            anomaly_metrics=(("service_p95_latency", 4),),
        ),
        window,
        Settings(),
    )
    assert "Thread 1/3 — SLI/SLO 상세 및 이상 분석" in payload["text"]
    assert "Thread 2/3 — 이상징후 / Incident 분석" in payload["text"]
    assert "Thread 3/3 — 오늘의 운영 조치" in payload["text"]
    assert "service_p95_latency: 4건" in payload["text"]


def test_threaded_daily_report_splits_parent_and_three_replies():
    window = ReportWindow.ending_at(datetime(2026, 8, 18, 9, 5, tzinfo=KST))
    parent, replies = format_threaded_daily_report(
        DailySnapshot(0, 0, 0, 100.0, 10.0), window, Settings()
    )
    assert "[REPORT]" in parent
    assert len(replies) == 3
    assert "Thread 1/3" in replies[0]
    assert "Thread 2/3" in replies[1]
    assert "Thread 3/3" in replies[2]


def test_empty_slo_environment_values_are_treated_as_unset():
    settings = Settings(
        daily_report_availability_slo="",
        daily_report_p95_latency_ms_slo="",
    )
    assert settings.daily_report_availability_slo is None
    assert settings.daily_report_p95_latency_ms_slo is None
