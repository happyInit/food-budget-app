"""Redis 잡 상태 · 교차유저 캐시 · 단일비행 락.

**왜 처음부터 Redis인가**: 잡 상태를 프로세스 메모리에 두면 replica를 늘리는 순간
"POST를 받은 파드"와 "GET을 받은 파드"가 달라져 결과를 못 찾는다. OCR이 이 문제로
`replicas: 1`에 묶여 있다(#296). 이 서비스는 상태를 처음부터 외부화해 **replica-safe로 시작**한다(#298).

Redis 장애 시 동작: 잡 저장/조회는 실패해야 정직하다(결과를 잃은 걸 숨기면 안 됨).
반면 **캐시·락은 best-effort** — 장애 시 그냥 재분석하면 되지 요청을 막을 이유가 없다.

🔴 **재시도는 잡 상태 경로에만 건다** (체크리스트 `1-14` · C-14 ElastiCache 전환의 명시적 선행).
ElastiCache Multi-AZ 페일오버는 **DNS 이름이 유지된 채 뒤의 노드가 바뀌어 기존 커넥션이 끊긴다.**
`video` 는 사용자가 화면 앞에서 기다리는 온디맨드 경로라 그 짧은 창이 그대로 "분석 실패"로 보인다.
캐시·락에는 **일부러 안 건다** — 거기는 빨리 포기하고 재분석하는 게 정답이라 재시도가 후퇴다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.config import settings

_JOB = "video:job:{}"        # 잡 상태(JSON)
_CACHE = "video:recipe:{}"   # 정규화 URL → 추출 결과(JSON)
_LOCK = "video:lock:{}"      # 단일비행 — 같은 URL 동시 요청 중복 분석 방지
_SPEND = "video:spend"       # 유료 호출 누적 건수 — 월 예산 브레이크(TTL 로 자동 리셋)

_log = logging.getLogger("video")
_T = TypeVar("_T")

# 재시도 대상 = **연결 계열만**. 그 밖(응답 파싱·타입 오류 등)은 재시도해도 같은 결과라
# 그대로 올린다 — `pipelines/stream/_dlq.py` 가 쓰는 원칙과 같다("아는 것만 처리").
_RETRYABLE = (RedisConnectionError, RedisTimeoutError)


def make_redis() -> Redis:
    """잡 상태·캐시·락 공용 클라이언트. lifespan 에서 1회 생성해 재사용한다(main.py).

    `health_check_interval` = 유휴 커넥션을 재사용하기 전에 PING 으로 살아 있는지 본다.
    ElastiCache Multi-AZ 페일오버(C-14)는 **DNS 이름이 유지된 채 뒤의 노드가 바뀌므로**
    풀에 남은 옛 소켓이 죽은 채로 재사용될 수 있다. 이게 없으면 그 첫 명령이 실패한다.
    """
    return Redis(host=settings.redishost, port=settings.redisport,
                 decode_responses=True, socket_timeout=3, socket_connect_timeout=3,
                 health_check_interval=settings.redis_health_check_s)


async def _retrying(op: Callable[[], Awaitable[_T]], what: str) -> _T:
    """연결 계열 실패만 재시도한다(지수 백오프). 소진되면 마지막 예외를 그대로 올린다.

    ⚠️ **클라이언트 레벨 `retry=` 를 쓰지 않는 이유** — redis-py 의 retry 는 **전 명령**에 걸린다.
    그러면 캐시·락까지 백오프를 기다린 뒤에야 except 로 떨어져, *"빨리 포기하고 재분석"* 이
    정답인 경로가 오히려 느려진다(= 개선이 아니라 후퇴). 그래서 재시도를 **잡 상태 두 메서드에만**
    좁혀 건다. 위 docstring 의 3층 정책(잡=fail-loud / 캐시·락=best-effort)을 그대로 지킨다.

    🔴 재시도해도 실패하면 **여전히 예외를 올린다** — 재시도는 실패를 없애는 게 아니라
       페일오버 창을 덮을 뿐이고, 잡 상태는 "실패해야 정직한" 경로다.

    ⏱ **최악 지연 = 약 9.2초** (3회 × `socket_timeout` 3s + 백오프 0.05+0.1).
       종전 3초에서 6초 늘었다. 이 대가를 받아들인 근거:
         · 짧은 페일오버는 2~3번째 시도에서 **성공**한다 — 사용자는 오류를 아예 안 본다(= 목적)
         · 긴 장애는 어차피 오류다. 3초에 실패하든 9초에 실패하든 결과가 같다
         · 이 기능은 영상 분석에 **최대 120초**(`video_timeout_s`)를 쓰는 경로다. 9초는 그 안에서 작다
       🔴 다만 공개 게이트웨이 타임아웃이 **전부 `0s`(무제한)** 라(체크리스트 `1-11`)
          이 9.2초를 잘라줄 상위 계층이 **없다**. `1-11`·`1-36` 이 들어오면 그 값이 상한이 된다.
    """
    last: BaseException | None = None
    for attempt in range(settings.redis_job_retries):
        try:
            return await op()
        except _RETRYABLE as exc:
            last = exc
            if attempt == settings.redis_job_retries - 1:
                break
            delay = settings.redis_job_retry_base_s * (2 ** attempt)
            _log.warning(
                "redis job op failed, retrying",
                extra={"event": "redis_retry", "op": what, "attempt": attempt + 1,
                       "error_type": type(exc).__name__, "retryable": True},
            )
            await asyncio.sleep(delay)
    _log.error(
        "redis job op exhausted retries",
        extra={"event": "redis_retry_exhausted", "op": what,
               "attempts": settings.redis_job_retries,
               "error_type": type(last).__name__, "retryable": False},
    )
    raise last  # type: ignore[misc]


class Store:
    def __init__(self, redis: Redis) -> None:
        self._r = redis

    # ── 잡 상태(실패를 숨기지 않음 · 연결 계열만 재시도) ───────────────
    #    재시도는 ElastiCache 페일오버 창(C-14)을 덮기 위한 것이지 실패를 감추려는 게 아니다.
    #    소진되면 예외가 그대로 호출부로 올라가 사용자에게 오류가 보인다 — 그게 이 경로의 정책이다.
    async def put_job(self, job_id: str, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False)
        await _retrying(
            lambda: self._r.set(_JOB.format(job_id), body, ex=settings.job_ttl_s), "put_job")

    async def get_job(self, job_id: str) -> dict | None:
        raw = await _retrying(lambda: self._r.get(_JOB.format(job_id)), "get_job")
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

    # ── 월 예산 브레이크 ──────────────────────────────────────────────
    async def try_spend(self) -> bool:
        """유료 분석 1건을 예산에서 차감한다. 예산이 남았으면 True.

        🔴 **INCR 로 먼저 올리고 초과면 거절**한다 — "읽고→판단하고→올리는" 순서면
           동시 요청이 같은 값을 읽어 상한을 넘겨 통과한다(check-then-act 경합).
        🔴 **Redis 가 죽으면 통과시킨다**(fail-open). 이건 과금 방어지 인증이 아니고,
           캐시 장애로 기능이 통째로 멈추는 쪽이 더 나쁘다 — 위 캐시·락과 같은 판단이다.
           ⚠️ 그래서 이 상한은 **최후 방어선이 아니다.** 진짜 하드스톱은 Google 쪽
              청구 상한이고, 이건 그 앞에서 우아하게 멈추는 층이다.
        """
        if not settings.video_monthly_cap_enabled:
            return True
        limit = int(settings.video_monthly_budget_won / max(settings.video_cost_per_call_won, 0.01))
        try:
            used = await self._r.incr(_SPEND)
            if used == 1:   # 창의 첫 건에만 TTL 을 건다 → 그 시점부터 한 달
                await self._r.expire(_SPEND, settings.video_monthly_cap_window_s)
            if used > limit:
                _log.warning("video 월 예산 소진 — 사용 %d / 상한 %d 건", used, limit)
                return False
            return True
        except Exception:  # noqa: BLE001
            _log.warning("video 예산 카운터 접근 실패 — 통과시킨다(fail-open)")
            return True

    async def ping(self) -> bool:
        try:
            return bool(await self._r.ping())
        except Exception:  # noqa: BLE001
            return False
