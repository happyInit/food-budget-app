from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.kubernetes_evidence import KubernetesEvidenceCollector
from app.models import IncidentCandidate, NormalizedAlert


class FakeKubernetesApiClient:
    def __init__(self, resources):
        self._resources = resources

    async def list_items(self, path, *, label_selector=None):
        return self._resources[path]


def _incident() -> IncidentCandidate:
    started_at = datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)
    alert = NormalizedAlert(
        alert_id="recipe-latency",
        status="firing",
        alert_name="AppHighP95Latency",
        service="recipe",
        severity="warning",
        starts_at=started_at,
        received_at=started_at,
        labels={"service": "recipe"},
        annotations={},
    )
    return IncidentCandidate(
        incident_id="incident-recipe-latency",
        title="recipe incident candidate",
        first_seen_at=started_at,
        last_seen_at=started_at + timedelta(minutes=5),
        earliest_alert_id=alert.alert_id,
        earliest_alert_name=alert.alert_name,
        suspected_origin_service="recipe",
        affected_services=["recipe", "gateway"],
        alert_count=1,
        grouping_reasons=["same_service"],
        alerts=[alert],
    )


def test_collects_incident_scoped_kubernetes_events_and_deployments():
    namespace = "app"
    resources = {
        f"/api/v1/namespaces/{namespace}/events": [
            {
                "metadata": {
                    "uid": "backoff-1",
                    "namespace": namespace,
                    "creationTimestamp": "2026-07-30T10:02:00Z",
                },
                "involvedObject": {"kind": "Pod", "name": "mp-recipe-abc"},
                "reason": "BackOff",
                "message": "Back-off restarting failed container",
                "type": "Warning",
                "count": 3,
            },
            {
                "metadata": {"uid": "unrelated-1", "creationTimestamp": "2026-07-30T10:02:00Z"},
                "involvedObject": {"kind": "Pod", "name": "mp-price-abc"},
                "reason": "OOMKilled",
                "message": "container was killed",
            },
        ],
        f"/api/v1/namespaces/{namespace}/pods": [
            {"metadata": {"name": "mp-recipe-abc", "labels": {"app": "recipe"}}},
            {"metadata": {"name": "mp-price-abc", "labels": {"app": "price"}}},
        ],
        f"/apis/apps/v1/namespaces/{namespace}/deployments": [
            {
                "metadata": {
                    "name": "mp-recipe",
                    "namespace": namespace,
                    "labels": {"app": "recipe"},
                    "creationTimestamp": "2026-07-30T09:55:00Z",
                },
                "spec": {"template": {"spec": {"containers": [{"image": "harbor/mp-recipe:4fda555"}]}}},
                "status": {"observedGeneration": 3},
            }
        ],
        f"/apis/apps/v1/namespaces/{namespace}/replicasets": [
            {
                "metadata": {
                    "name": "mp-recipe-7f856f",
                    "creationTimestamp": "2026-07-30T09:55:30Z",
                    "ownerReferences": [{"kind": "Deployment", "name": "mp-recipe"}],
                }
            }
        ],
    }
    collector = KubernetesEvidenceCollector(
        Settings(operations_kubernetes_namespace=namespace),
        client=FakeKubernetesApiClient(resources),
    )
    incident = _incident()

    bundle = asyncio.run(
        collector.collect(
            incident,
            start_at=incident.first_seen_at - timedelta(minutes=15),
            end_at=incident.last_seen_at + timedelta(minutes=15),
        )
    )

    assert [event.event_id for event in bundle.events] == ["backoff-1"]
    assert bundle.events[0].count == 3
    assert len(bundle.deployments) == 1
    assert bundle.deployments[0].replica_set == "mp-recipe-7f856f"
    assert bundle.deployments[0].git_sha == "4fda555"
