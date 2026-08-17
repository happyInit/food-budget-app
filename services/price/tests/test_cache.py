"""읽기 캐시(stale-while-revalidate + single-flight) — DB·Redis 없이 도는 테스트.

🔴 이 파일이 지키는 것은 성능이 아니라 **동시성 계약**이다.
   2026-08-17 AWS Stage1 부하시험에서 핫딜 캐시가 만료되는 순간 약 715건이 동시에 같은
   쿼리로 몰려(캐시 스탬피드) PG 커넥션이 고갈되고 max 45.19초 · 5xx 1,783건이 났다.
   "미스 시 각자 조회" 로 되돌아가면 그 사고가 그대로 재현되므로, 여기서 **조회 횟수**를 못박는다.

pytest-asyncio 를 안 쓴다 — price 는 그 의존성이 없고, 이것 때문에 requirements 를 늘리면
Dockerfile 인라인 핀과 진실이 둘이 된다. `asyncio.run` 으로 충분하다.
"""
from __future__ import annotations

import asyncio

from app import main
from app.config import settings


class FakeRedis:
    """TTL 은 흉내내지 않는다 — 테스트가 키를 직접 심어 신선/stale 상태를 만든다."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def mget(self, keys):
        return [self.data.get(k) for k in keys]

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None                      # 락 경쟁 패배
        self.data[key] = value
        return True

    async def delete(self, key):
        self.data.pop(key, None)


def _run(coro):
    """코루틴을 돌린 뒤 백그라운드 갱신 태스크까지 끝낸다(루프가 닫히기 전에)."""

    async def _wrapper():
        result = await coro()
        while main._refresh_tasks:
            await asyncio.gather(*list(main._refresh_tasks), return_exceptions=True)
        return result

    return asyncio.run(_wrapper())


def _producer(value, delay=0.05):
    """호출 횟수를 세는 produce. delay 가 있어야 동시 요청이 실제로 겹친다."""
    calls = []

    async def produce():
        calls.append(1)
        await asyncio.sleep(delay)
        return value

    return produce, calls


KEY = "price:hotdeals:20"
TTL = 120


def test_fresh_hit_does_not_query():
    """신선하면 produce 를 아예 안 부른다 — 기존 read-through 와 같은 성질."""
    main.state["redis"] = FakeRedis()
    main.state["redis"].data.update({KEY: "OLD", f"{KEY}:fresh": "1"})
    produce, calls = _producer("NEW")

    assert _run(lambda: main.cached_json(KEY, TTL, produce)) == "OLD"
    assert calls == []


def test_cold_stampede_queries_once():
    """🔴 핵심 — 캐시가 빈 상태로 20건이 동시에 와도 **조회는 1회**."""
    main.state["redis"] = FakeRedis()
    produce, calls = _producer("VALUE")

    async def burst():
        return await asyncio.gather(*[main.cached_json(KEY, TTL, produce) for _ in range(20)])

    results = _run(burst)
    assert results == ["VALUE"] * 20        # 진 쪽도 승자의 결과를 받아 간다(실패로 만들지 않는다)
    assert len(calls) == 1                  # 스탬피드였다면 20회였다


def test_stale_serves_old_value_and_refreshes_once():
    """만료돼도 **옛 값이 즉시** 나가고, 갱신은 하나만 뒤에서 한다."""
    main.state["redis"] = FakeRedis()
    main.state["redis"].data[KEY] = "OLD"   # payload 만 있고 :fresh 가 없다 = stale
    produce, calls = _producer("NEW")

    async def burst():
        return await asyncio.gather(*[main.cached_json(KEY, TTL, produce) for _ in range(20)])

    results = _run(burst)
    assert results == ["OLD"] * 20          # 🔴 아무도 기다리지 않는다 — 이게 SWR 의 요점
    assert len(calls) == 1
    assert main.state["redis"].data[KEY] == "NEW"        # 갱신은 됐다
    assert f"{KEY}:lock" not in main.state["redis"].data  # 락도 풀렸다


def test_refresh_failure_keeps_serving_stale():
    """갱신이 실패해도 옛 값은 계속 나가고, 락이 남지 않아 다음 요청이 재시도할 수 있다."""
    main.state["redis"] = FakeRedis()
    main.state["redis"].data[KEY] = "OLD"

    async def produce():
        raise RuntimeError("PG down")

    assert _run(lambda: main.cached_json(KEY, TTL, produce)) == "OLD"
    assert main.state["redis"].data[KEY] == "OLD"
    assert f"{KEY}:lock" not in main.state["redis"].data


def test_cache_unavailable_falls_through_to_query():
    """🔵 캐시가 없으면 **기존과 똑같이** 각자 조회해서 응답한다(best-effort 유지)."""
    main.state["redis"] = None
    produce, calls = _producer("VALUE", delay=0)

    assert _run(lambda: main.cached_json(KEY, TTL, produce)) == "VALUE"
    assert len(calls) == 1


def test_none_result_is_not_cached():
    """404(=None)는 캐시하지 않는다 — 품목이 생기면 즉시 반영돼야 한다."""
    main.state["redis"] = FakeRedis()

    async def produce():
        return None

    assert _run(lambda: main.cached_json("price:current:999", 300, produce)) is None
    assert "price:current:999" not in main.state["redis"].data


def test_stale_ttl_settings_are_sane():
    """유예가 TTL 보다 짧으면 SWR 이 사실상 꺼진다 — 값이 뒤집히는 것을 막는다."""
    assert settings.cache_stale_ttl_s >= settings.cache_hotdeals_ttl_s
    assert settings.cache_lock_ttl_s > settings.cache_cold_wait_s
