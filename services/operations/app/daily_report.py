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
    incident_titles: tuple[str, ...] = ()
    anomaly_metrics: tuple[tuple[str, int], ...] = ()


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
            await cur.execute(
                """select title from operations.incidents
                   where first_seen_at <= %s and last_seen_at >= %s
                   order by last_seen_at desc limit 5""",
                (window.end, window.start),
            )
            incident_titles = tuple(row["title"] for row in await cur.fetchall())
            await cur.execute(
                """select metric_id, count(*) as count from operations.anomalies
                   where evaluated_at between %s and %s and status = 'anomaly'
                   group by metric_id order by count desc, metric_id limit 5""",
                (window.start, window.end),
            )
            anomaly_metrics = tuple(
                (row["metric_id"], int(row["count"])) for row in await cur.fetchall()
            )
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
        incident_titles=incident_titles,
        anomaly_metrics=anomaly_metrics,
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
    source_state = "⚠️ 일부 수집 실패" if snapshot.source_errors else "✅ Prometheus·Operations DB 수집 정상"
    incident_lines = (
        [f"• {title}" for title in snapshot.incident_titles]
        if snapshot.incident_titles
        else ["• 보고 구간 Incident 없음"]
    )
    anomaly_lines = (
        [f"• {metric}: {count}건" for metric, count in snapshot.anomaly_metrics]
        if snapshot.anomaly_metrics
        else ["• 확정 이상징후 없음"]
    )
    action_lines = (
        ["• P1: 현재 미해결 Incident를 대시보드에서 우선 확인"]
        if snapshot.open_incident_count
        else ["• P2: 이상징후 추세와 배포 검증 대상은 대시보드에서 확인"]
        if snapshot.anomaly_count
        else ["• 오늘 즉시 조치가 필요한 Operations Incident 없음"]
    )
    lines = [
        "📊 *[REPORT] Operations 일일 리포트*",
        f"*상태:* {status}",
        f"*대상 구간:* {window.start:%Y-%m-%d %H:%M} ~ {window.end:%Y-%m-%d %H:%M} KST",
        "",
        "*요약*",
        f"지난 24시간 동안 이상징후 {snapshot.anomaly_count}건, 보고 구간 Incident {snapshot.incident_count}건, 현재 미해결 Incident {snapshot.open_incident_count}건을 확인했습니다.",
        "",
        "*기본 지표*",
        f"• 가용성: {availability} / SLO {target_availability}",
        f"• p95 응답시간: {p95} / SLO {target_p95}",
        f"• 이상징후: {snapshot.anomaly_count}건 · 구간 Incident: {snapshot.incident_count}건 · 현재 미해결: {snapshot.open_incident_count}건",
        "",
        "*근거 데이터 상태*",
        source_state,
    ]
    if snapshot.source_errors:
        lines.extend([*[f"⚠️ {error}" for error in snapshot.source_errors]])
    lines.extend([
        "",
        "*TL;DR*",
        "사용자 영향 지표와 조사 후보는 대시보드에서 세부 근거를 확인하세요. SLO가 미설정인 지표는 준수/위반 판정을 하지 않습니다.",
        "",
        "*Thread 1/3 — SLI/SLO 상세 및 이상 분석*",
        f"• 24시간 가용성: {availability} / 목표 {target_availability}",
        f"• 24시간 p95: {p95} / 목표 {target_p95}",
        "• Error Budget·Burn Rate: SLO 목표 합의 후 활성화",
        "",
        "*Thread 2/3 — 이상징후 / Incident 분석*",
        *anomaly_lines,
        "Incident:",
        *incident_lines,
        "",
        "*Thread 3/3 — 오늘의 운영 조치*",
        *action_lines,
        f"• 상세 대시보드: {settings.operations_dashboard_base_url.rstrip('/')}",
    ])
    return {"text": "\n".join(lines)}


def format_threaded_daily_report(
    snapshot: DailySnapshot, window: ReportWindow, settings: Settings
) -> tuple[str, tuple[str, str, str]]:
    """Build a Slack parent message and three native-thread replies.

    An Incoming Webhook cannot obtain the parent's ``ts``.  Slack Web API,
    using a bot token, returns it so the detailed messages can be attached as
    genuine Slack thread replies instead of merely looking like threads.
    """
    status = "🔴 조치 필요" if snapshot.open_incident_count else "🟡 추적 필요" if snapshot.anomaly_count else "🟢 정상"
    availability = "데이터 없음" if snapshot.availability_percent is None else f"{snapshot.availability_percent:.3f}%"
    p95 = "데이터 없음" if snapshot.p95_latency_ms is None else f"{snapshot.p95_latency_ms:.0f}ms"
    target_availability = "미설정" if settings.daily_report_availability_slo is None else f"{settings.daily_report_availability_slo * 100:.3f}%"
    target_p95 = "미설정" if settings.daily_report_p95_latency_ms_slo is None else f"{settings.daily_report_p95_latency_ms_slo:.0f}ms"
    source_state = "⚠️ 일부 수집 실패" if snapshot.source_errors else "✅ Prometheus·Operations DB 수집 정상"
    anomaly_lines = [f"• {metric}: {count}건" for metric, count in snapshot.anomaly_metrics] or ["• 확정 이상징후 없음"]
    incident_lines = [f"• {title}" for title in snapshot.incident_titles] or ["• 보고 구간 Incident 없음"]
    action_lines = (
        ["• P1: 현재 미해결 Incident를 대시보드에서 우선 확인"]
        if snapshot.open_incident_count
        else ["• P2: 이상징후 추세와 배포 검증 대상은 대시보드에서 확인"]
        if snapshot.anomaly_count
        else ["• 오늘 즉시 조치가 필요한 Operations Incident 없음"]
    )
    parent = "\n".join([
        "📊 *[REPORT] Operations 일일 리포트*",
        f"*상태:* {status}",
        f"*대상 구간:* {window.start:%Y-%m-%d %H:%M} ~ {window.end:%Y-%m-%d %H:%M} KST",
        "",
        "*기본 지표*",
        f"• 가용성: {availability} / SLO {target_availability}",
        f"• p95 응답시간: {p95} / SLO {target_p95}",
        f"• 이상징후: {snapshot.anomaly_count}건 · 구간 Incident: {snapshot.incident_count}건 · 현재 미해결: {snapshot.open_incident_count}건",
        "",
        f"*근거 데이터 상태:* {source_state}",
        *[f"⚠️ {error}" for error in snapshot.source_errors],
        f"상세: {settings.operations_dashboard_base_url.rstrip('/')}",
    ])
    sli_detail = "\n".join([
        "*Thread 1/3 — SLI/SLO 상세 및 이상 분석*",
        f"• 24시간 가용성: {availability} / 목표 {target_availability}",
        f"• 24시간 p95: {p95} / 목표 {target_p95}",
        "• Error Budget·Burn Rate: SLO 목표 합의 후 활성화",
    ])
    anomaly_detail = "\n".join([
        "*Thread 2/3 — 이상징후 / Incident 분석*",
        *anomaly_lines,
        "Incident:",
        *incident_lines,
    ])
    action_detail = "\n".join([
        "*Thread 3/3 — 오늘의 운영 조치*",
        *action_lines,
        f"• 상세 대시보드: {settings.operations_dashboard_base_url.rstrip('/')}",
    ])
    return parent, (sli_detail, anomaly_detail, action_detail)


async def _send_threaded_report(settings: Settings, snapshot: DailySnapshot, window: ReportWindow) -> None:
    parent, replies = format_threaded_daily_report(snapshot, window, settings)
    headers = {"Authorization": f"Bearer {settings.daily_report_slack_bot_token}"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers=headers,
            json={"channel": settings.daily_report_slack_channel_id, "text": parent},
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("ok") or not body.get("ts"):
            raise RuntimeError(f"Slack parent post failed: {body.get('error', 'missing ts')}")
        for reply in replies:
            response = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers=headers,
                json={
                    "channel": settings.daily_report_slack_channel_id,
                    "thread_ts": body["ts"],
                    "text": reply,
                },
            )
            response.raise_for_status()
            if not response.json().get("ok"):
                raise RuntimeError("Slack thread reply post failed")


async def send_daily_report(settings: Settings, now: datetime | None = None) -> None:
    if not settings.daily_report_enabled:
        raise RuntimeError("DAILY_REPORT_ENABLED=true is required")
    has_bot_threading = bool(
        settings.daily_report_slack_bot_token and settings.daily_report_slack_channel_id
    )
    if not has_bot_threading and not settings.daily_report_slack_webhook_url:
        raise RuntimeError(
            "DAILY_REPORT_SLACK_WEBHOOK_URL or both DAILY_REPORT_SLACK_BOT_TOKEN "
            "and DAILY_REPORT_SLACK_CHANNEL_ID are required"
        )
    window = ReportWindow.ending_at(now or datetime.now(timezone.utc))
    snapshot = await collect_snapshot(settings, window)
    if has_bot_threading:
        await _send_threaded_report(settings, snapshot, window)
        return
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(settings.daily_report_slack_webhook_url, json=format_daily_report(snapshot, window, settings))
        response.raise_for_status()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # httpx includes full request URLs in its INFO access log.  The Slack
    # Incoming Webhook URL is a bearer secret, so do not let a routine report
    # run write it into systemd/Docker logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(send_daily_report(Settings()))


if __name__ == "__main__":  # pragma: no cover - exercised by the systemd job
    main()
