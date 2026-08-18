"""Investigation-candidate Slack message for newly created Incidents.

Deliberately separate from Alertmanager's own Slack route
(mp-alertmanager-slack, wired in infra's kube-prometheus-stack values) —
that webhook carries Prometheus-authored alert text and must keep working
even if this code has a bug. A failure here is swallowed, never raised,
so a dead/misconfigured webhook cannot block Alert ingestion (the caller,
ingest_alertmanager_webhook, must still persist Alerts and build Incidents).
"""

from __future__ import annotations

import logging

import httpx

from app.config import Settings
from app.models import IncidentCandidate

logger = logging.getLogger(__name__)


def format_incident_pre_alert(incident: IncidentCandidate, *, dashboard_base_url: str) -> dict:
    """Build an evidence-bound RCA investigation candidate, not a verdict."""
    detail_url = f"{dashboard_base_url.rstrip('/')}/incidents/{incident.incident_id}"
    services = ", ".join(incident.affected_services) or incident.suspected_origin_service
    alert_lines = [
        f"• {alert.alert_name} · {alert.service} · {alert.severity}"
        for alert in incident.alerts
    ] or ["• 수집된 Alert 상세 없음"]
    labels = incident.alerts[0].labels if incident.alerts else {}
    namespace = labels.get("namespace", "<namespace>")
    pod = incident.alerts[0].pod if incident.alerts else None
    target = pod or labels.get("instance") or services
    commands = [
        f"kubectl get events -n {namespace} --sort-by=.lastTimestamp | tail -30",
        f"kubectl get pods -n {namespace} -o wide",
    ]
    if pod:
        commands.insert(0, f"kubectl describe pod {pod} -n {namespace}")
        commands.append(f"kubectl logs {pod} -n {namespace} --since=15m")
    return {
        "text": (
            f"🔎 *[AI 조사 후보] {incident.suspected_origin_service}*\n\n"
            f"*탐지 정보*\n"
            f"• 탐지 시각: {incident.first_seen_at:%Y-%m-%d %H:%M UTC}\n"
            f"• 대상: {target}\n"
            f"• 영향 서비스: {services}\n"
            f"• 연관 Alert: {incident.alert_count}건\n"
            f"• Incident candidate: 예\n\n"
            f"*선정 사유*\n"
            + "\n".join(f"• {reason}" for reason in incident.grouping_reasons)
            + f"\n\n*관측 근거*\n"
            + "\n".join(alert_lines)
            + f"\n\n*가능 원인*\n"
            f"1. {incident.suspected_origin_service}의 Alert 조건 충족\n"
            f"2. 연관 Alert·Pod 이벤트·최근 변경사항 추가 확인 필요\n"
            f"확신도: 낮음 (자동 RCA 전 후보 단계)\n\n"
            f"*권장 조치*\n"
            f"P0 · 즉시 확인\n"
            + "\n".join(f"• `{command}`" for command in commands)
            + f"\n\nP1 · 원인 분리\n"
            f"• 대시보드에서 동일 시간대 이상징후·로그·트레이스·배포 이벤트를 비교\n"
            f"• 실제 변경 작업은 운영자 확인 후 수행\n\n"
            f"*상세:* {detail_url}"
        )
    }


async def send_incident_pre_alert(
    incident: IncidentCandidate,
    *,
    settings: Settings,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Best-effort Slack notification. Returns False (never raises) on any failure.

    ``client`` is injectable so unit tests do not need a real webhook or
    network access.
    """
    if not settings.operations_slack_webhook_url:
        return False
    payload = format_incident_pre_alert(
        incident, dashboard_base_url=settings.operations_dashboard_base_url
    )
    try:
        if client is not None:
            response = await client.post(settings.operations_slack_webhook_url, json=payload)
        else:
            async with httpx.AsyncClient(timeout=5.0) as owned_client:
                response = await owned_client.post(
                    settings.operations_slack_webhook_url, json=payload
                )
        response.raise_for_status()
        return True
    except Exception:
        logger.warning(
            "failed to send Incident pre-alert to Slack for incident_id=%s",
            incident.incident_id,
            exc_info=True,
        )
        return False
