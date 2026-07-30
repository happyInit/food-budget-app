"""Redis 잡 상태 · 교차유저 캐시 · 단일비행 락.

**왜 처음부터 Redis인가**: 잡 상태를 프로세스 메모리에 두면 replica를 늘리는 순간
"POST를 받은 파드"와 "GET을 받은 파드"가 달라져 결과를 못 찾는다. OCR이 이 문제로
`replicas: 1`에 묶여 있다(#296). 이 서비스는 상태를 처음부터 외부화해 **replica-safe로 시작**한다(#298).

Redis 장애 시 동작: 잡 저장/조회는 실패해야 정직하다(결과를 잃은 걸 숨기면 안 됨).
반면 **캐시·락은 best-effort** — 장애 시 그냥 재분석하면 되지 요청을 막을 이유가 없다.
"""
from __future__ import annotations

import json

from redis.asyncio import Redis

from app.config import settings

_JOB = "video:job:{}"        # 잡 상태(JSON)
_CACHE = "video:recipe:{}"   # 정규화 URL → 추출 결과(JSON)
_LOCK = "video:lock:{}"      # 단일비행 — 같은 URL 동시 요청 중복 분석 방지


def make_redis() -> Redis:
    return Redis(host=settings.redishost, port=settings.redisport,
                 decode_responses=True, socket_timeout=3, socket_connect_timeout=3)


class Store:
    def __init__(self, redis: Redis) -> None:
        self._r = redis

    # ── 잡 상태(실패를 숨기지 않음) ───────────────────────────────────
    async def put_job(self, job_id: str, payload: dict) -> None:
        await self._r.set(_JOB.format(job_id), json.dumps(payload, ensure_ascii=False),
                          ex=settings.job_ttl_s)

    async def get_job(self, job_id: str) -> dict | None:
        raw = await self._r.get(_JOB.format(job_id))
        return json.loads(raw) if raw else None

    # ── 교차유저 캐시(best-effort) ────────────────────────────────────
    # 같은 영상을 다른 유저가 요청하면 Gemini 호출 없이 즉시 응답 = 비용 0.
    async def get_cached(self, norm_url: str) -> dict | None:
        try:
            raw = await self._r.get(_CACHE.format(norm_url))
            return json.loads(raw) if raw else None
        except Exception:  # noqa: BLE001 — 캐시 장애로 요청을 막지 않는다
            return None

    async def set_cached(self, norm_url: str, recipe: dict) -> None:
        try:
            await self._r.set(_CACHE.format(norm_url), json.dumps(recipe, ensure_ascii=False),
                              ex=settings.cache_ttl_s)
        except Exception:  # noqa: BLE001
            pass

    # ── 단일비행 락(best-effort) ──────────────────────────────────────
    async def acquire(self, norm_url: str) -> bool:
        """같은 URL이 이미 분석 중이면 False. 락 실패 시 True(분석 진행) — 중복 비용보다 가용성 우선."""
        try:
            return bool(await self._r.set(_LOCK.format(norm_url), "1", nx=True, ex=settings.lock_ttl_s))
        except Exception:  # noqa: BLE001
            return True

    async def release(self, norm_url: str) -> None:
        try:
            await self._r.delete(_LOCK.format(norm_url))
        except Exception:  # noqa: BLE001
            pass

    async def ping(self) -> bool:
        try:
            return bool(await self._r.ping())
        except Exception:  # noqa: BLE001
            return False
