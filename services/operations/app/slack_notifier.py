"""Pre-alert Slack summary for newly created Incidents (helpdesk mode).

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
    """Build the Slack message payload for one newly created Incident.

    Kept short and factual (title, origin, affected services, alert count) —
    this is a "something happened, go look" ping, not an analysis. Anything
    resembling root-cause reasoning belongs to RCA/chat, not this notifier.
    """
    detail_url = f"{dashboard_base_url.rstrip('/')}/incidents/{incident.incident_id}"
    services = ", ".join(incident.affected_services) or incident.suspected_origin_service
    return {
        "text": (
            f"🔔 새 Incident: {incident.title}\n"
            f"영향 서비스: {services}\n"
            f"연관 Alert {incident.alert_count}건\n"
            f"자세히 보기: {detail_url}\n"
            f"대시보드 챗봇에서 이 Incident를 열고 '무슨 사항이야?'라고 물어보세요."
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
