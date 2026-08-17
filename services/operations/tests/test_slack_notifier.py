from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from app.config import Settings
from app.models import IncidentCandidate
from app.slack_notifier import format_incident_pre_alert, send_incident_pre_alert


def _incident() -> IncidentCandidate:
    seen_at = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
    return IncidentCandidate(
        incident_id="incident-kurly-stale",
        title="컬리 크롤러 정지",
        first_seen_at=seen_at,
        last_seen_at=seen_at,
        earliest_alert_id="kurly-stale-critical",
        earliest_alert_name="MpKurlyDataStaleCritical",
        suspected_origin_service="data-pipeline",
        affected_services=["data-pipeline"],
        alert_count=1,
        grouping_reasons=["same_service"],
        alerts=[],
    )


def test_format_incident_pre_alert_includes_title_and_detail_link():
    payload = format_incident_pre_alert(
        _incident(), dashboard_base_url="https://ops.example.com"
    )

    assert "[AI 조사 후보]" in payload["text"]
    assert "https://ops.example.com/incidents/incident-kurly-stale" in payload["text"]
    assert "data-pipeline" in payload["text"]
    assert "권장 조치" in payload["text"]


def test_send_incident_pre_alert_skips_silently_without_webhook_url():
    settings = Settings(operations_slack_webhook_url="")

    sent = asyncio.run(send_incident_pre_alert(_incident(), settings=settings))

    assert sent is False


def test_send_incident_pre_alert_posts_to_configured_webhook():
    settings = Settings(operations_slack_webhook_url="https://hooks.slack.example/T000/B000/xxx")
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        return httpx.Response(200, json={"ok": True})

    async def run() -> bool:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await send_incident_pre_alert(_incident(), settings=settings, client=client)

    sent = asyncio.run(run())

    assert sent is True
    assert len(requests_seen) == 1
    assert str(requests_seen[0].url) == settings.operations_slack_webhook_url


def test_send_incident_pre_alert_returns_false_without_raising_on_webhook_failure():
    """A dead/misconfigured webhook must never break Alert ingestion."""
    settings = Settings(operations_slack_webhook_url="https://hooks.slack.example/T000/B000/xxx")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    async def run() -> bool:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await send_incident_pre_alert(_incident(), settings=settings, client=client)

    sent = asyncio.run(run())

    assert sent is False
