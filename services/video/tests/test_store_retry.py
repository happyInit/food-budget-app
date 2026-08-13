"""잡 상태 경로 재시도 — 체크리스트 `1-14`(C-14 ElastiCache 전환의 명시적 선행).

검증하는 것은 **정책**이다:
  ① 연결 계열 실패는 재시도한다 (페일오버 창을 덮는다)
  ② 재시도해도 실패하면 **예외를 올린다** (잡 상태는 "실패해야 정직한" 경로)
  ③ 연결 계열이 아닌 예외는 **재시도하지 않는다** (영구 실패를 반복하지 않는다)
  ④ 캐시·락에는 재시도가 **걸리지 않는다** (빨리 포기하는 게 정답인 경로)

Redis 드라이버 없이 돈다 — FakeRedis 로 호출 횟수만 센다(DB-free 컨벤션, services/CONVENTIONS.md).
"""
from __future__ import annotations

import json

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import settings
from app.store import Store


class _FlakyRedis:
    """앞의 `fail_times` 번은 지정 예외를 던지고 그 뒤 성공하는 가짜 클라이언트."""

    def __init__(self, fail_times: int, exc: BaseException, value: str | None = None) -> None:
        self._left = fail_times
        self._exc = exc
        self._value = value
        self.calls = 0

    async def _maybe_fail(self):
        self.calls += 1
        if self._left > 0:
            self._left -= 1
            raise self._exc
        return self._value

    async def set(self, *_a, **_k):
        return await self._maybe_fail()

    async def get(self, *_a, **_k):
        return await self._maybe_fail()

    async def delete(self, *_a, **_k):
        return await self._maybe_fail()


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch):
    """백오프를 0 으로 — 테스트가 실제로 기다릴 이유가 없다."""
    monkeypatch.setattr(settings, "redis_job_retry_base_s", 0.0)
    monkeypatch.setattr(settings, "redis_job_retries", 3)


# ── ① 연결 계열은 재시도한다 ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_put_job_retries_connection_error_then_succeeds():
    r = _FlakyRedis(fail_times=2, exc=RedisConnectionError("failover"))
    await Store(r).put_job("j1", {"status": "PENDING"})
    assert r.calls == 3          # 2회 실패 + 1회 성공


@pytest.mark.asyncio
async def test_get_job_retries_connection_error_then_succeeds():
    payload = json.dumps({"status": "DONE"})
    r = _FlakyRedis(fail_times=1, exc=RedisConnectionError("failover"), value=payload)
    got = await Store(r).get_job("j1")
    assert got == {"status": "DONE"} and r.calls == 2


# ── ② 소진되면 예외를 올린다 (실패를 숨기지 않는다) ──────────────────
@pytest.mark.asyncio
async def test_put_job_raises_after_retries_exhausted():
    r = _FlakyRedis(fail_times=99, exc=RedisConnectionError("down"))
    with pytest.raises(RedisConnectionError):
        await Store(r).put_job("j1", {"status": "PENDING"})
    assert r.calls == settings.redis_job_retries   # 무한 재시도하지 않는다


# ── ③ 연결 계열이 아니면 재시도하지 않는다 ───────────────────────────
@pytest.mark.asyncio
async def test_non_connection_error_is_not_retried():
    r = _FlakyRedis(fail_times=99, exc=ValueError("bad payload"))
    with pytest.raises(ValueError):
        await Store(r).get_job("j1")
    assert r.calls == 1          # 🔴 재시도해도 같은 결과 — 즉시 올린다


# ── ④ 캐시·락은 재시도하지 않는다 (degrade 가 정답) ──────────────────
@pytest.mark.asyncio
async def test_cache_does_not_retry_and_degrades():
    r = _FlakyRedis(fail_times=99, exc=RedisConnectionError("down"))
    assert await Store(r).get_cached("https://x") is None   # 예외 없이 캐시 미스
    assert r.calls == 1                                     # 기다리지 않는다


@pytest.mark.asyncio
async def test_lock_does_not_retry_and_proceeds():
    r = _FlakyRedis(fail_times=99, exc=RedisConnectionError("down"))
    assert await Store(r).acquire("https://x") is True      # 락 실패 시 분석 진행
    assert r.calls == 1
