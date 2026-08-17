"""Daily Operations report job.

Run as a one-shot process, outside the FastAPI server:
``python -m app.daily_report``.  The host scheduler owns *when* it runs;
this module only assembles an auditable 24-hour Operations digest and posts it
to the dedicated Slack webhook.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings
from app.db import make_pg_pool
from app.prometheus_client import PrometheusClient, PrometheusQueryError

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class ReportWindow:
    start: datetime
    end: datetime

    @classmethod
    def ending_at(cls, now: datetime) -> "ReportWindow":
        """Return the operational day ending at 09:00 KST.

        The timer runs at 09:05 to absorb scrape and webhook delays, but the
        data window itself must remain stable: 09:00 yesterday through 08:59
        today.  A manual run before 09:00 reports the preceding operational
        day rather than a partial day.
        """
        local_now = now.astimezone(KST)
        end = local_now.replace(hour=9, minute=0, second=0, microsecond=0)
        if local_now < end:
            end -= timedelta(days=1)
        return cls(start=end - timedelta(hours=24), end=end)


@dataclass(frozen=True)
class DailySnapshot:
    incident_count: int
    open_incident_count: int
    anomaly_count: int
    availability_percent: float | None
    p95_latency_ms: float | None
    source_errors: tuple[str, ...] = ()


async def _scalar(client: PrometheusClient, promql: str, at: datetime) -> float | None:
    try:
        series = await client.query(promql, at=at)
    except (httpx.HTTPError, PrometheusQueryError) as error:
        raise RuntimeError(f"Prometheus query failed: {error}") from error
    if not series or not series[0].points:
        return None
    return series[0].points[0].value


async def collect_snapshot(settings: Settings, window: ReportWindow) -> DailySnapshot:
    """Read the same Operations sources used by the dashboard.

    Source failures are recorded in the digest rather than being converted
    into a false green result.  The report remains useful for DB-only events
    when Prometheus is temporarily unavailable.
    """
    pool = make_pg_pool(settings)
    await pool.open()
    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """select count(*) as count from operations.incidents
                   where first_seen_at <= %s and last_seen_at >= %s""",
                (window.end, window.start),
            )
            incident_count = int((await cur.fetchone())["count"])
            await cur.execute("select count(*) as count from operations.incidents where status = 'open'")
            open_incident_count = int((await cur.fetchone())["count"])
            await cur.execute(
                """select count(*) as count from operations.anomalies
                   where evaluated_at between %s and %s and status = 'anomaly'""",
                (window.start, window.end),
            )
            anomaly_count = int((await cur.fetchone())["count"])
    finally:
        await pool.close()

    errors: list[str] = []
    availability_percent: float | None = None
    p95_latency_ms: float | None = None
    prom = PrometheusClient(settings.operations_prometheus_url)
    try:
        # Keep the metric names aligned with metric_catalog.py/dashboard.
        total = await _scalar(
            prom,
            'sum(increase(http_requests_total{namespace="app",service!~".*-canary"}[24h]))',
            window.end,
        )
        failures = await _scalar(
            prom,
            'sum(increase(http_requests_total{namespace="app",service!~".*-canary",status=~"5.."}[24h]))',
            window.end,
        )
        if total is not None and total > 0 and failures is not None:
            availability_percent = 100 * (1 - failures / total)
        p95_latency_ms = await _scalar(
            prom,
            'histogram_quantile(0.95, sum by(le) (increase(http_request_duration_highr_seconds_bucket{namespace="app"}[24h]))) * 1000',
            window.end,
        )
    except RuntimeError as error:
        errors.append(str(error))

    return DailySnapshot(
        incident_count=incident_count,
        open_incident_count=open_incident_count,
        anomaly_count=anomaly_count,
        availability_percent=availability_percent,
        p95_latency_ms=p95_latency_ms,
        source_errors=tuple(errors),
    )


def format_daily_report(snapshot: DailySnapshot, window: ReportWindow, settings: Settings) -> dict:
    status = "🔴 조치 필요" if snapshot.open_incident_count else "🟡 추적 필요" if snapshot.anomaly_count else "🟢 정상"
    availability = "데이터 없음" if snapshot.availability_percent is None else f"{snapshot.availability_percent:.3f}%"
    p95 = "데이터 없음" if snapshot.p95_latency_ms is None else f"{snapshot.p95_latency_ms:.0f}ms"
    target_availability = (
        "미설정" if settings.daily_report_availability_slo is None
        else f"{settings.daily_report_availability_slo * 100:.3f}%"
    )
    target_p95 = (
        "미설정" if settings.daily_report_p95_latency_ms_slo is None
        else f"{settings.daily_report_p95_latency_ms_slo:.0f}ms"
    )
    lines = [
        "📊 *[REPORT] Operations 일일 리포트*",
        f"*상태:* {status}",
        f"*대상 구간:* {window.start:%Y-%m-%d %H:%M} ~ {window.end:%Y-%m-%d %H:%M} KST",
        "",
        "*기본 지표*",
        f"• 가용성: {availability} / SLO {target_availability}",
        f"• p95 응답시간: {p95} / SLO {target_p95}",
        f"• 이상징후: {snapshot.anomaly_count}건 · 구간 Incident: {snapshot.incident_count}건 · 미해결: {snapshot.open_incident_count}건",
    ]
    if snapshot.source_errors:
        lines.extend(["", "*근거 데이터 상태*", *[f"⚠️ {error}" for error in snapshot.source_errors]])
    lines.extend(["", f"상세: {settings.operations_dashboard_base_url.rstrip('/')}"])
    return {"text": "\n".join(lines)}


async def send_daily_report(settings: Settings, now: datetime | None = None) -> None:
    if not settings.daily_report_enabled:
        raise RuntimeError("DAILY_REPORT_ENABLED=true is required")
    if not settings.daily_report_slack_webhook_url:
        raise RuntimeError("DAILY_REPORT_SLACK_WEBHOOK_URL is required")
    window = ReportWindow.ending_at(now or datetime.now(timezone.utc))
    snapshot = await collect_snapshot(settings, window)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(settings.daily_report_slack_webhook_url, json=format_daily_report(snapshot, window, settings))
        response.raise_for_status()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(send_daily_report(Settings()))


if __name__ == "__main__":  # pragma: no cover - exercised by the systemd job
    main()
