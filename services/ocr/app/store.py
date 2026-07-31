"""OCR 잡 상태 저장소 — Redis 외부화(#296).

**왜 필요한가**: 잡 상태를 프로세스 메모리에 두면 replica를 늘리는 순간
"POST를 받은 파드"와 "GET을 받은 파드"가 달라져 결과를 못 찾는다(404).
그래서 OCR은 `replicas: 1` · HPA 없음으로 묶여 있었다(`ai-services-deploy-spec.md §3`).
상태를 Redis로 옮기면 이 제약이 풀리고 다중 replica·HPA가 가능해진다.

**폴백 정책**: Redis가 없거나 죽으면 **인메모리로 계속 동작**한다.
  - 단일 replica 환경(로컬 개발·현행 배포)에서는 이것으로 충분하다.
  - 다만 그 상태로 replica를 늘리면 다시 #296이 재현되므로, 기동 시 경고를 남긴다.
  - "Redis 없으면 서비스 자체를 거부"는 과하다 — OCR 본질(이미지→JSON)은 Redis와 무관하다.
"""
from __future__ import annotations

import json
import logging

from app.config import settings
from app.models import OcrStatusResponse

log = logging.getLogger("ocr.store")

_KEY = "ocr:job:{}"


class JobStore:
    """Redis 우선, 실패 시 인메모리 폴백."""

    def __init__(self, redis=None) -> None:
        self._redis = redis
        self._mem: dict[str, OcrStatusResponse] = {}

    @property
    def backing(self) -> str:
        return "redis" if self._redis is not None else "memory"

    async def put(self, job_id: str, status: OcrStatusResponse) -> None:
        if self._redis is not None:
            try:
                await self._redis.set(
                    _KEY.format(job_id),
                    status.model_dump_json(),
                    ex=settings.job_ttl_s,
                )
                return
            except Exception:  # noqa: BLE001 — Redis 장애로 잡을 잃지 않도록 메모리에 남긴다
                log.warning("Redis put 실패 — 인메모리 폴백 (job=%s)", job_id)
        self._mem[job_id] = status

    async def get(self, job_id: str) -> OcrStatusResponse | None:
        if self._redis is not None:
            try:
                raw = await self._redis.get(_KEY.format(job_id))
                if raw is not None:
                    return OcrStatusResponse(**json.loads(raw))
            except Exception:  # noqa: BLE001
                log.warning("Redis get 실패 — 인메모리 조회 (job=%s)", job_id)
        return self._mem.get(job_id)

    async def ping(self) -> bool:
        if self._redis is None:
            return False
        try:
            return bool(await self._redis.ping())
        except Exception:  # noqa: BLE001
            return False


def make_store() -> JobStore:
    """설정에 Redis 호스트가 있으면 연결해서 붙인다. 실패해도 서비스는 뜬다."""
    if not settings.redishost:
        log.warning("REDISHOST 미설정 — 인메모리 잡 상태. ⚠️ replicas>1 이면 #296 재현")
        return JobStore(None)
    try:
        from redis.asyncio import Redis

        client = Redis(
            host=settings.redishost, port=settings.redisport,
            decode_responses=True, socket_timeout=3, socket_connect_timeout=3,
        )
        return JobStore(client)
    except Exception as exc:  # noqa: BLE001
        log.warning("Redis 연결 실패(%s) — 인메모리 폴백. ⚠️ replicas>1 이면 #296 재현",
                    type(exc).__name__)
        return JobStore(None)
