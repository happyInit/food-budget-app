from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.models import (
    DeploymentEvidence,
    IncidentCandidate,
    KubernetesEventEvidence,
)


_RELEVANT_EVENT_REASONS = {
    "BackOff",
    "CrashLoopBackOff",
    "FailedScheduling",
    "OOMKilled",
    "OOMKilling",
    "ScalingReplicaSet",
    "SuccessfulRescale",
    "Unhealthy",
}
_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")


@dataclass(frozen=True)
class KubernetesEvidenceBundle:
    events: list[KubernetesEventEvidence]
    deployments: list[DeploymentEvidence]


class KubernetesApiClient:
    """Small read-only Kubernetes API client used only for incident evidence."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    async def list_items(
        self, path: str, *, label_selector: str | None = None
    ) -> list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self._token()}"}
        params = {"labelSelector": label_selector} if label_selector else None
        if self._client is not None:
            response = await self._client.get(path, headers=headers, params=params)
        else:
            async with httpx.AsyncClient(
                base_url=self._settings.operations_kubernetes_api_url,
                verify=self._settings.operations_kubernetes_ca_path,
                timeout=10.0,
            ) as client:
                response = await client.get(path, headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()
        return payload.get("items", [])

    def _token(self) -> str:
        return Path(self._settings.operations_kubernetes_token_path).read_text().strip()


class KubernetesEvidenceCollector:
    """Collect selected Kubernetes Event and deployment context for one Incident."""

    def __init__(self, settings: Settings, client: KubernetesApiClient | None = None) -> None:
        self._settings = settings
        self._client = client or KubernetesApiClient(settings)

    async def collect(
        self,
        incident: IncidentCandidate,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> KubernetesEvidenceBundle:
        namespace = self._settings.operations_kubernetes_namespace
        events = await self._client.list_items(f"/api/v1/namespaces/{namespace}/events")
        pods = await self._client.list_items(f"/api/v1/namespaces/{namespace}/pods")
        deployments = await self._client.list_items(
            f"/apis/apps/v1/namespaces/{namespace}/deployments"
        )
        replica_sets = await self._client.list_items(
            f"/apis/apps/v1/namespaces/{namespace}/replicasets"
        )
        services = {incident.suspected_origin_service, *incident.affected_services}
        selected_pods = self._service_pods(pods, services)
        return KubernetesEvidenceBundle(
            events=self._select_events(events, selected_pods, start_at, end_at),
            deployments=self._select_deployments(
                deployments, replica_sets, services, namespace
            ),
        )

    @staticmethod
    def _service_pods(pods: list[dict[str, Any]], services: set[str]) -> set[str]:
        selected: set[str] = set()
        for pod in pods:
            metadata = pod.get("metadata", {})
            name = metadata.get("name", "")
            labels = metadata.get("labels", {})
            service = labels.get("app") or labels.get("app.kubernetes.io/name")
            if service in services or any(
                name.startswith(f"mp-{item}-") for item in services
            ):
                selected.add(name)
        return selected

    def _select_events(
        self,
        events: list[dict[str, Any]],
        selected_pods: set[str],
        start_at: datetime,
        end_at: datetime,
    ) -> list[KubernetesEventEvidence]:
        selected: list[KubernetesEventEvidence] = []
        for event in events:
            involved = event.get("involvedObject", {})
            pod = involved.get("name") if involved.get("kind") == "Pod" else None
            reason = event.get("reason", "")
            message = event.get("message", "")
            if pod not in selected_pods or not self._is_relevant_event(reason, message):
                continue
            occurred_at = self._event_time(event)
            if occurred_at is None or not start_at <= occurred_at <= end_at:
                continue
            metadata = event.get("metadata", {})
            series = event.get("series", {})
            selected.append(
                KubernetesEventEvidence(
                    namespace=metadata.get(
                        "namespace", self._settings.operations_kubernetes_namespace
                    ),
                    event_id=metadata.get("uid", metadata.get("name", "unknown-event")),
                    reason=reason,
                    message=message,
                    event_type=event.get("type"),
                    occurred_at=occurred_at,
                    count=int(series.get("count") or event.get("count") or 1),
                    pod=pod,
                    selection_reasons=["incident_time_window", "incident_service_pod"],
                )
            )
        return sorted(selected, key=lambda item: (item.occurred_at, item.event_id))

    @staticmethod
    def _is_relevant_event(reason: str, message: str) -> bool:
        return reason in _RELEVANT_EVENT_REASONS or any(
            term in message for term in ("CrashLoopBackOff", "OOMKilled", "Unhealthy")
        )

    @staticmethod
    def _event_time(event: dict[str, Any]) -> datetime | None:
        series = event.get("series", {})
        for value in (
            event.get("eventTime"),
            series.get("lastObservedTime"),
            event.get("lastTimestamp"),
            event.get("metadata", {}).get("creationTimestamp"),
        ):
            if value:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                    timezone.utc
                )
        return None

    @staticmethod
    def _select_deployments(
        deployments: list[dict[str, Any]],
        replica_sets: list[dict[str, Any]],
        services: set[str],
        namespace: str,
    ) -> list[DeploymentEvidence]:
        replica_sets_by_deployment: dict[str, list[dict[str, Any]]] = {}
        for replica_set in replica_sets:
            for owner in replica_set.get("metadata", {}).get("ownerReferences", []):
                if owner.get("kind") == "Deployment":
                    replica_sets_by_deployment.setdefault(owner.get("name", ""), []).append(
                        replica_set
                    )

        evidence: list[DeploymentEvidence] = []
        for deployment in deployments:
            metadata = deployment.get("metadata", {})
            labels = metadata.get("labels", {})
            name = metadata.get("name", "")
            service = labels.get("app") or labels.get("app.kubernetes.io/name")
            if service not in services and name.removeprefix("mp-") not in services:
                continue
            replica_set = max(
                replica_sets_by_deployment.get(name, []),
                key=lambda item: item.get("metadata", {}).get("creationTimestamp", ""),
                default=None,
            )
            containers = (
                deployment.get("spec", {})
                .get("template", {})
                .get("spec", {})
                .get("containers", [])
            )
            for container in containers:
                image = container.get("image")
                if not image:
                    continue
                image_tag = (
                    image.rsplit(":", 1)[-1]
                    if ":" in image.rsplit("/", 1)[-1]
                    else None
                )
                evidence.append(
                    DeploymentEvidence(
                        namespace=metadata.get("namespace", namespace),
                        deployment=name,
                        replica_set=(replica_set or {}).get("metadata", {}).get("name"),
                        image=image,
                        image_tag=image_tag,
                        git_sha=image_tag if image_tag and _SHA_PATTERN.fullmatch(image_tag) else None,
                        observed_generation=deployment.get("status", {}).get("observedGeneration"),
                        created_at=datetime.fromisoformat(
                            metadata["creationTimestamp"].replace("Z", "+00:00")
                        ).astimezone(timezone.utc),
                        selection_reasons=[
                            "incident_affected_service",
                            "deployment_image_context",
                        ],
                    )
                )
        return sorted(evidence, key=lambda item: (item.deployment, item.image))
