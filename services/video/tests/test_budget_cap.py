"""월 예산 브레이크 — 영상 분석은 우리 유료 경로 중 가장 비싸다(건당 ~87원).

검증하는 것은 **정책**이다:
  ① 예산 안에서는 통과하고, 넘으면 거절한다
  ② 카운터에 **TTL 이 창의 첫 건에만** 걸린다 (매 건 갱신하면 창이 영원히 안 닫힌다)
  ③ Redis 장애면 **통과시킨다**(fail-open) — 과금 방어지 인증이 아니다
  ④ 플래그를 끄면 Redis 를 아예 건드리지 않는다
  ⑤ 상한 판정은 **INCR 결과**로 한다 (읽고→판단하고→올리면 동시 요청이 상한을 넘긴다)

Redis 드라이버 없이 돈다 — FakeRedis 로 센다(DB-free 컨벤션, services/CONVENTIONS.md).
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.store import Store


class _CountingRedis:
    """INCR 을 실제로 세는 최소 가짜. expire 호출도 기록한다."""

    def __init__(self) -> None:
        self.n = 0
        self.expire_calls = 0

    async def incr(self, _key):
        self.n += 1
        return self.n

    async def expire(self, _key, _ttl):
        self.expire_calls += 1
        return True


class _BrokenRedis:
    async def incr(self, _key):
        raise RuntimeError("redis down")

    async def expire(self, _key, _ttl):
        raise RuntimeError("redis down")


@pytest.fixture
def cap(monkeypatch):
    """예산 3건짜리 창 — 87원 × 3 = 261원."""
    monkeypatch.setattr(settings, "video_monthly_cap_enabled", True)
    monkeypatch.setattr(settings, "video_monthly_budget_won", 261)
    monkeypatch.setattr(settings, "video_cost_per_call_won", 87.0)


@pytest.mark.asyncio
async def test_예산_안에서는_통과하고_넘으면_거절한다(cap):
    r = _CountingRedis()
    s = Store(r)
    assert [await s.try_spend() for _ in range(3)] == [True, True, True]
    # 4번째부터는 예산 밖 — 상한이 실제로 문을 닫는다
    assert await s.try_spend() is False
    assert await s.try_spend() is False


@pytest.mark.asyncio
async def test_TTL은_창의_첫_건에만_걸린다(cap):
    """🔴 매 건 expire 를 다시 걸면 트래픽이 있는 한 창이 영원히 안 닫혀
    '월' 예산이 사실상 '영구' 예산이 된다."""
    r = _CountingRedis()
    s = Store(r)
    for _ in range(3):
        await s.try_spend()
    assert r.expire_calls == 1


@pytest.mark.asyncio
async def test_redis_장애면_통과시킨다(cap):
    """과금 방어지 인증이 아니다 — 캐시 장애로 기능이 통째로 멈추는 쪽이 더 나쁘다.
    ⚠️ 그래서 이건 최후 방어선이 아니다. 하드스톱은 Google 청구 상한이다."""
    assert await Store(_BrokenRedis()).try_spend() is True


@pytest.mark.asyncio
async def test_플래그_끄면_redis를_건드리지_않는다(monkeypatch):
    monkeypatch.setattr(settings, "video_monthly_cap_enabled", False)
    r = _CountingRedis()
    assert await Store(r).try_spend() is True
    assert r.n == 0            # INCR 조차 안 나간다


@pytest.mark.asyncio
async def test_동시요청도_상한을_못_넘는다(cap):
    """INCR 결과로 판정하므로, 같은 순간에 몰려도 통과 건수는 상한을 넘지 않는다.
    (읽고→판단하고→올리는 순서였다면 여기서 4건 이상이 통과한다)"""
    import asyncio
    s = Store(_CountingRedis())
    got = await asyncio.gather(*[s.try_spend() for _ in range(10)])
    assert sum(got) == 3
