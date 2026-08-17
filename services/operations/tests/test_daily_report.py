from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.daily_report import DailySnapshot, ReportWindow, format_daily_report


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
