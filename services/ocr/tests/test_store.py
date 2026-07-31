"""잡 상태 저장소 — #296(replica-safe) 회귀 방지.

인메모리 저장은 "POST 받은 파드 != GET 받은 파드"일 때 결과를 잃는다.
아래 테스트는 **Redis 없이도** 그 계약을 검증한다(가짜 Redis로 공유 저장소를 흉내).
"""
import json

import pytest

from app.models import OcrItemOut, OcrStatusResponse
from app.store import JobStore


class _FakeRedis:
    """여러 JobStore가 공유하는 저장소 — 다중 파드가 같은 Redis를 보는 상황."""

    def __init__(self, fail=False):
        self.data, self.fail = {}, fail

    async def set(self, k, v, ex=None):
        if self.fail:
            raise ConnectionError("redis down")
        self.data[k] = v

    async def get(self, k):
        if self.fail:
            raise ConnectionError("redis down")
        return self.data.get(k)

    async def ping(self):
        if self.fail:
            raise ConnectionError("redis down")
        return True


@pytest.mark.asyncio
async def test_job_visible_across_pods():
    """#296의 핵심 — A가 저장한 잡을 B가 조회할 수 있어야 다중 replica가 가능하다."""
    shared = _FakeRedis()
    pod_a, pod_b = JobStore(shared), JobStore(shared)

    await pod_a.put("j1", OcrStatusResponse(status="PENDING"))
    assert (await pod_b.get("j1")).status == "PENDING"

    await pod_a.put("j1", OcrStatusResponse(
        status="DONE", store="GS25 역삼점", total_amount=16300.0, backend="mock",
        items=[OcrItemOut(raw_text="삼겹살 8,900", name="삼겹살", price=8900.0,
                          category="식재료", storage="FRIDGE")]))
    got = await pod_b.get("j1")
    assert got.status == "DONE" and got.store == "GS25 역삼점"
    assert got.items[0].name == "삼겹살" and got.items[0].storage == "FRIDGE"


@pytest.mark.asyncio
async def test_inmemory_is_isolated_per_pod():
    """폴백(인메모리)에서는 격리된다 — 이 상태로 replicas>1 하면 안 된다는 근거."""
    pod_a, pod_b = JobStore(None), JobStore(None)
    await pod_a.put("j2", OcrStatusResponse(status="DONE"))
    assert await pod_b.get("j2") is None
    assert pod_a.backing == "memory"


@pytest.mark.asyncio
async def test_redis_failure_falls_back_without_losing_job():
    """Redis가 죽어도 잡을 잃지 않는다(같은 파드 안에서는 계속 동작)."""
    store = JobStore(_FakeRedis(fail=True))
    await store.put("j3", OcrStatusResponse(status="PENDING"))
    got = await store.get("j3")
    assert got is not None and got.status == "PENDING"
    assert await store.ping() is False


@pytest.mark.asyncio
async def test_unknown_job_returns_none():
    assert await JobStore(_FakeRedis()).get("nope") is None


@pytest.mark.asyncio
async def test_roundtrip_preserves_all_fields():
    """직렬화 왕복에서 분류 결과(category/storage/in_expense/needs_review)가 보존돼야 한다."""
    shared = _FakeRedis()
    src = OcrStatusResponse(
        status="DONE", store="이마트", purchased_at="2026-07-16 19:32:00",
        total_amount=9600.0, backend="vision",
        items=[OcrItemOut(raw_text="종량제봉투 3,500", name="종량제봉투", price=3500.0,
                          is_food=False, category="비식품", storage=None,
                          in_expense=False, needs_review=True)])
    await JobStore(shared).put("j4", src)
    got = await JobStore(shared).get("j4")
    assert got.model_dump() == json.loads(src.model_dump_json())
