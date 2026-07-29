from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.models import (
    AlertIngestionResult,
    AlertmanagerAlert,
    AlertmanagerWebhook,
    NormalizedAlert,
)


class AlertNormalizer:
    """Convert Alertmanager webhooks into the Operations alert contract."""

    def normalize(self, payload: AlertmanagerWebhook) -> AlertIngestionResult:
        received_at = datetime.now(timezone.utc)
        alerts = [
            self._normalize_alert(alert, received_at=received_at) for alert in payload.alerts
        ]
        return AlertIngestionResult(
            group_key=payload.group_key,
            receiver=payload.receiver,
            received_alert_count=len(alerts),
            alerts=alerts,
        )

    @staticmethod
    def _normalize_alert(
        alert: AlertmanagerAlert, *, received_at: datetime
    ) -> NormalizedAlert:
        labels = alert.labels
        alert_name = labels.get("alertname", "unknown")
        service = (
            labels.get("service")
            or labels.get("container")
            or labels.get("job")
            or "unknown"
        )
        fingerprint = alert.fingerprint or _fallback_alert_id(
            alert_name=alert_name,
            starts_at=alert.starts_at,
            labels=labels,
        )
        return NormalizedAlert(
            alert_id=fingerprint,
            status=alert.status,
            alert_name=alert_name,
            service=service,
            severity=labels.get("severity", "warning"),
            starts_at=alert.starts_at,
            ends_at=alert.ends_at,
            received_at=received_at,
            pod=labels.get("pod"),
            container=labels.get("container"),
            labels=labels,
            annotations=alert.annotations,
            generator_url=alert.generator_url,
        )


def _fallback_alert_id(
    *, alert_name: str, starts_at: datetime, labels: dict[str, str]
) -> str:
    stable_payload = json.dumps(
        {
            "alert_name": alert_name,
            "starts_at": starts_at.isoformat(),
            "labels": labels,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(stable_payload.encode()).hexdigest()
