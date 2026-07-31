from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.models import TimeSeriesPoint


class PrometheusQueryError(RuntimeError):
    pass


@dataclass(frozen=True)
class PrometheusSeries:
    labels: dict[str, str]
    points: list[TimeSeriesPoint]


class PrometheusClient:
    """Small async client for the Prometheus HTTP query API."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client

    async def query_range(
        self,
        promql: str,
        *,
        start: datetime,
        end: datetime,
        step_seconds: int,
    ) -> list[PrometheusSeries]:
        response = await self._request(
            "/api/v1/query_range",
            {
                "query": promql,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": step_seconds,
            },
        )
        return self._parse_matrix(response)

    async def query(self, promql: str, *, at: datetime) -> list[PrometheusSeries]:
        response = await self._request(
            "/api/v1/query",
            {"query": promql, "time": at.timestamp()},
        )
        result = response.get("data", {}).get("result", [])
        series: list[PrometheusSeries] = []
        for item in result:
            value = item.get("value")
            if not isinstance(value, list) or len(value) != 2:
                continue
            point = self._parse_point(value)
            if point is not None:
                series.append(PrometheusSeries(labels=item.get("metric", {}), points=[point]))
        return series

    async def _request(self, path: str, params: dict[str, object]) -> dict:
        if self._client is not None:
            response = await self._client.get(f"{self._base_url}{path}", params=params)
        else:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(f"{self._base_url}{path}", params=params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            raise PrometheusQueryError(str(payload.get("error", "Prometheus query failed")))
        return payload

    def _parse_matrix(self, payload: dict) -> list[PrometheusSeries]:
        result = payload.get("data", {}).get("result", [])
        series: list[PrometheusSeries] = []
        for item in result:
            points = [
                point
                for raw_point in item.get("values", [])
                if (point := self._parse_point(raw_point)) is not None
            ]
            if points:
                series.append(PrometheusSeries(labels=item.get("metric", {}), points=points))
        return series

    @staticmethod
    def _parse_point(raw_point: object) -> TimeSeriesPoint | None:
        if not isinstance(raw_point, list) or len(raw_point) != 2:
            return None
        try:
            value = float(raw_point[1])
            timestamp = datetime.fromtimestamp(float(raw_point[0]), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None
        if not math.isfinite(value):
            return None
        return TimeSeriesPoint(timestamp=timestamp, value=value)
